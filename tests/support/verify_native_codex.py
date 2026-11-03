"""Opt-in native acceptance using a fresh offline CODEX_HOME, never personal sessions.

uv run python -m tests.support.verify_native_codex --executable /absolute/path/to/codex
The only model endpoint is closed loopback port 9. No credentials are copied.
"""

import argparse
import fcntl
import json
import os
import pty
import select
import selectors
import signal
import sqlite3
import struct
import subprocess
import tempfile
import termios
import time
from pathlib import Path

MARKER = "SYNTHETIC-RESUME-CONTEXT"


class Server:
    def __init__(self, executable, cwd, env):
        self.child = subprocess.Popen(
            [str(executable), "app-server", "--stdio"],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.child.stdout, selectors.EVENT_READ)
        self.pending, self.sequence = b"", 0
        self.call(
            "initialize",
            {
                "clientInfo": {"name": "sessions-manager-validation", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.child.stdin.write(b'{"method":"initialized"}\n')
        self.child.stdin.flush()

    def call(self, method, params):
        self.sequence += 1
        self.child.stdin.write(
            (json.dumps({"id": self.sequence, "method": method, "params": params}) + "\n").encode()
        )
        self.child.stdin.flush()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            while b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                value = json.loads(line)
                if value.get("id") == self.sequence:
                    assert "result" in value, f"Native method failed: {method}"
                    return value["result"]
            if self.selector.select(0.1):
                chunk = os.read(self.child.stdout.fileno(), 1048576)
                if not chunk:
                    break
                self.pending += chunk
        raise AssertionError(f"Native method timed out: {method}")

    def close(self):
        self.child.stdin.close()
        try:
            self.child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.child.terminate()
            self.child.wait(timeout=3)
        self.child.stdout.close()
        self.selector.close()


def native_ui(executable, tid, cwd, env):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    child = subprocess.Popen(
        [str(executable), "--no-daemon", "resume", tid, "-C", str(cwd), "--no-alt-screen"],
        cwd=cwd,
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    output = b""
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and child.poll() is None:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                output += chunk
                if b"\x1b[6n" in chunk:
                    os.write(master, b"\x1b[1;1R")
                if b"\x1b[c" in chunk:
                    os.write(master, b"\x1b[?1;2c")
                if MARKER.encode() in output:
                    return True
        return False
    finally:
        if child.poll() is None:
            os.write(master, b"\x03")
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=3)
        os.close(master)


def verify(executable):
    os.umask(0o077)
    base = Path(tempfile.mkdtemp(prefix="sessions-native-codex-"))
    home, project = base / "codex-home", base / "original-project"
    home.mkdir(mode=0o700)
    project.mkdir(mode=0o700)
    (home / "config.toml").write_text(
        'model_provider="offline"\nmodel="synthetic-model"\n[model_providers.offline]\nname="offline"\nbase_url="http://127.0.0.1:9/v1"\nwire_api="responses"\nrequires_openai_auth=false\n[analytics]\nenabled=false\n'
    )
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR"}}
    env.update(CODEX_HOME=str(home), TERM="xterm-256color")
    version = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, check=True, timeout=2
    ).stdout.strip()
    assert version == "codex-cli 0.166.0", "Unverified native version"
    server = Server(executable, project, env)
    try:
        neighbor = server.call(
            "thread/start", {"cwd": str(project), "historyMode": "paginated", "ephemeral": False}
        )["thread"]["id"]
        server.call(
            "turn/start",
            {"threadId": neighbor, "input": [{"type": "text", "text": "SYNTHETIC-NEIGHBOR"}]},
        )
        thread = server.call(
            "thread/start", {"cwd": str(project), "historyMode": "paginated", "ephemeral": False}
        )["thread"]
        tid = thread["id"]
        assert not thread.get("path") or not Path(thread["path"]).exists()
        server.call("turn/start", {"threadId": tid, "input": [{"type": "text", "text": MARKER}]})

    finally:
        server.close()
    server = Server(executable, project, env)
    try:
        result = server.call("thread/resume", {"threadId": tid})
        assert result["thread"]["id"] == tid and MARKER in json.dumps(result)
        server.call("thread/archive", {"threadId": tid})
        with sqlite3.connect((home / "state_5.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            assert db.execute("SELECT archived FROM threads WHERE id=?", (tid,)).fetchone()[0] == 1
            assert (
                db.execute("SELECT archived FROM threads WHERE id=?", (neighbor,)).fetchone()[0]
                == 0
            )
        restored = server.call("thread/unarchive", {"threadId": tid})["thread"]
        assert restored["id"] == tid
        assert MARKER in json.dumps(
            server.call("thread/read", {"threadId": tid, "includeTurns": True})
        )
    finally:
        server.close()
    moved = base / "moved-project"
    project.rename(moved)
    assert native_ui(executable, tid, moved, env), "Native UI did not load the recorded context"
    with sqlite3.connect((home / "state_5.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT cwd,history_mode,archived FROM threads WHERE id=?", (tid,)
        ).fetchone()
        assert Path(row[0]).resolve() == moved.resolve() and row[1:] == ("paginated", 0)
        assert db.execute("SELECT count(*) FROM threads").fetchone()[0] == 2
        assert db.execute("SELECT archived FROM threads WHERE id=?", (neighbor,)).fetchone()[0] == 0
    receipt = {
        "version": version,
        "same_identity": True,
        "history_loaded_after_restart": True,
        "archive_unarchive": True,
        "neighbor_preserved": True,
        "missing_original_cwd": True,
        "cli_resume_loaded_context": True,
        "new_sessions_from_resume": 0,
    }
    (base / "receipt.json").write_text(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    assert args.executable.is_absolute() and args.executable.is_file()
    print(json.dumps(verify(args.executable)))
