"""Opt-in native loading proof, confined to disposable files with no network/keychain.

The parent HOME/environment is unchanged. Only the sandboxed native child receives a
fresh HOME; this represents default Grok/Cursor roots without touching real stores.
No prompt or AI turn is sent, and native output is inspected only for a generated marker.
"""

import fcntl
import hashlib
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time
import uuid
from pathlib import Path


def native_environment(root):
    home = root / "home"
    temporary = root / "native-tmp"
    temporary.mkdir(mode=0o700, exist_ok=True)
    return {
        "HOME": str(home),
        "TMPDIR": str(root),
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TERM": "xterm-256color",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "CLAUDE_CODE_TMPDIR": str(temporary),
        "CLAUDE_TMPDIR": str(temporary),
        "AGENT_CLI_CREDENTIAL_STORE": "file",
    }


def sandbox_command(root, executable, argv):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("native_gate_sandbox_unavailable")
    root, executable = root.resolve(), executable.resolve(strict=True)
    info = executable.stat()
    if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
        raise RuntimeError("native_gate_executable_unsafe")

    def quote(value):
        return json.dumps(str(value), ensure_ascii=False)

    profile = (
        "(version 1) (allow default) (deny network*) (deny mach-lookup) "
        '(deny file-write*) (deny file-read* (subpath "/Users") '
        f"(subpath {quote(Path.home().resolve())}) (subpath {quote(root.parent)}) "
        '(subpath "/Library/Keychains") (subpath "/private/tmp")) '
        f"(allow file-read* file-write* (subpath {quote(root)})) "
        '(allow file-write* (literal "/dev/null") (literal "/dev/tty")) '
        f"(allow file-read* (subpath {quote(executable.parent)})) "
        '(deny process-exec (literal "/usr/bin/security")) '
    )
    # realpath in a packaged launcher needs ancestor metadata, never user contents.
    for parent in executable.parents:
        profile += f"(allow file-read-metadata (literal {quote(parent)})) "
    path = root / "native-gate.sb"
    path.write_text(profile)
    path.chmod(0o600)
    return ["/usr/bin/sandbox-exec", "-f", str(path), str(executable), *argv]


def receipt(
    provider, *, marker_visible, same_id, same_cwd, no_new_sessions, neighbor_preserved=True
):
    facts = dict(
        marker_visible=marker_visible,
        same_id=same_id,
        same_cwd=same_cwd,
        no_new_sessions=no_new_sessions,
        neighbor_preserved=neighbor_preserved,
    )
    return {"provider": provider, **facts, "conversation_loaded": all(facts.values())}


def terminal_run(command, cwd, env, marker, *, timeout=12):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, __import__("struct").pack("HHHH", 40, 140, 0, 0))
    process = None
    data, observed_cwd = b"", None
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
        )
        os.close(slave)
        slave = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(data) < 1024 * 1024:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    block = os.read(master, 65536)
                except OSError:
                    break
                if not block:
                    break
                data += block
            if marker.encode() in data or process.poll() is not None:
                break
        if process.poll() is None:
            found = subprocess.run(
                ["/usr/sbin/lsof", "-a", "-p", str(process.pid), "-d", "cwd", "-Fn"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            observed_cwd = next(
                (line[1:] for line in found.stdout.splitlines() if line.startswith("n")), None
            )
    finally:
        if slave is not None:
            os.close(slave)
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Some native runtimes restrict process-group signalling. This
                # handle still identifies only the child created by this gate.
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except PermissionError:
                    process.kill()
                process.wait(timeout=2)
        os.close(master)
    hint = (
        "authentication_required"
        if any(
            s in data.lower()
            for s in (b"log in", b"login", b"sign in", b"api key", b"authenticate")
        )
        else "isolation_denied"
        if any(
            s in data.lower() for s in (b"eperm", b"operation not permitted", b"permission denied")
        )
        else "history_not_loaded"
    )
    return marker.encode() in data, observed_cwd, hint


def verify(provider, executable):
    from importlib import import_module

    from sessions_manager.discovery import adapter
    from sessions_manager.launch import build_request
    from sessions_manager.models import SourceRoot

    expected = {"claude": "2.1.299", "grok": "1.0.70", "cursor": "2026.10.22-27dcf5f"}[provider]
    executable = executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="sessions-native-resume-") as raw:
        root = Path(raw).resolve()
        (root / "home").mkdir(mode=0o700)
        project = root / "project with spaces"
        project.mkdir()
        env = native_environment(root)
        version = subprocess.run(
            sandbox_command(root, executable, ["--version"]),
            env=env,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        escaped = re.escape(expected)
        pattern = {
            "claude": rf"{escaped} \(Claude Code\)\s*",
            "grok": rf"grok {escaped} \([A-Za-z0-9]+\) \[stable\]\s*",
            "cursor": rf"{escaped}\s*",
        }[provider]
        if version.returncode or not re.fullmatch(pattern, version.stdout):
            raise RuntimeError("native_gate_profile_unverified")
        home = root / "home" / (".cursor" if provider == "cursor" else "." + provider)
        factory = import_module("tests.support." + provider + "_factory")
        native, neighbor = str(uuid.uuid4()), str(uuid.uuid4())
        marker = "SYNTHETIC-RESUME-" + uuid.uuid4().hex
        selected_path = factory.make(home, native, cwd=project, text=marker)
        neighbor_path = factory.make(home, neighbor, cwd=project, text="Synthetic neighbor")
        # The native Claude project key is fixture-only; discovery never infers cwd from it.
        if provider == "claude":
            project_dir = home / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", str(project))
            selected_path.parent.rename(project_dir)
            selected_path, neighbor_path = (
                project_dir / selected_path.name,
                project_dir / neighbor_path.name,
            )
        files = (
            [neighbor_path]
            if neighbor_path.is_file()
            else [p for p in neighbor_path.rglob("*") if p.is_file()]
        )
        hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        source = SourceRoot.create(
            provider, home, executable_path=executable, resume_context="native"
        )
        sessions = adapter(source).discover().sessions
        selected = next(s for s in sessions if s.native_id == native)
        before = {s.native_id for s in sessions}
        request = build_request(source, selected, root / "manager", target="current")
        visible, actual_cwd, hint = terminal_run(
            sandbox_command(root, executable, request.argv[1:]), project, env, marker
        )
        after = adapter(source).discover().sessions
        matching = next((s for s in after if s.native_id == native), None)
        result = receipt(
            provider,
            marker_visible=visible,
            same_id=matching is not None,
            same_cwd=actual_cwd == str(project)
            and matching is not None
            and matching.cwd == str(project),
            no_new_sessions={s.native_id for s in after} == before,
            neighbor_preserved=all(
                p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == digest
                for p, digest in hashes.items()
            ),
        )
        return result | {
            "profile": expected,
            "startup": "history_loaded" if result["conversation_loaded"] else hint,
            "network": "denied",
            "keychain": "denied",
            "personal_stores": "denied",
        }
