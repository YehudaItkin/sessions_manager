"""Opt-in offline native archive gate; synthetic stores only, never personal data.

uv run python -m tests.support.verify_native_codex_archive --executable /absolute/codex
Graph rows are fixture construction in a fresh disposable CODEX_HOME; application
archive code never writes native SQLite. No credentials or external model calls.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from tests.support.verify_native_codex import Server


def verify(executable, *, cli=None):
    version = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, check=True, timeout=2
    ).stdout.strip()
    assert version == "codex-cli 0.166.0"
    with tempfile.TemporaryDirectory(prefix="sessions-native-archive-") as temporary:
        base = Path(temporary)
        home, project = base / "home", base / "project"
        home.mkdir(mode=0o700)
        project.mkdir(mode=0o700)
        (home / "config.toml").write_text(
            'model_provider="offline"\nmodel="synthetic-model"\n'
            '[model_providers.offline]\nname="offline"\n'
            'base_url="http://127.0.0.1:9/v1"\nwire_api="responses"\n'
            "requires_openai_auth=false\n[analytics]\nenabled=false\n"
        )
        env = {
            k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR"}
        }
        env.update(CODEX_HOME=str(home), TERM="xterm-256color")
        ids = {}
        server = Server(executable, project, env)
        try:
            for name in ("parent", "child", "prior", "neighbor"):
                ids[name] = server.call(
                    "thread/start",
                    {
                        "cwd": str(project),
                        "historyMode": "paginated",
                        "ephemeral": False,
                    },
                )["thread"]["id"]
                server.call(
                    "turn/start",
                    {
                        "threadId": ids[name],
                        "input": [{"type": "text", "text": "SYNTHETIC-ARCHIVE-" + name}],
                    },
                )
        finally:
            server.close()
        # Controlled fixture topology, seeded only after the native writer stops.
        with sqlite3.connect(home / "state_5.sqlite") as db:
            for name in ("child", "prior"):
                db.execute(
                    "INSERT INTO thread_spawn_edges VALUES (?,?,?)",
                    (ids["parent"], ids[name], "completed"),
                )

        db.close()

        def flags():
            db = sqlite3.connect((home / "state_5.sqlite").as_uri() + "?mode=ro", uri=True)
            try:
                assert db.execute("SELECT COUNT(*) FROM threads").fetchone()[0] == len(ids)
                return {
                    name: bool(
                        db.execute("SELECT archived FROM threads WHERE id=?", (tid,)).fetchone()[0]
                    )
                    for name, tid in ids.items()
                }
            finally:
                db.close()

        def histories(server):
            return {
                name: server.call("thread/read", {"threadId": tid, "includeTurns": True})["thread"][
                    "turns"
                ]
                for name, tid in ids.items()
            }

        server = Server(executable, project, env)
        try:
            server.call("thread/archive", {"threadId": ids["prior"]})
            original = flags()
            before = histories(server)
            server.call("thread/archive", {"threadId": ids["parent"]})
            assert flags() == dict(parent=True, child=True, prior=True, neighbor=False)
        finally:
            server.close()
        server = Server(executable, project, env)
        try:
            server.call("thread/unarchive", {"threadId": ids["parent"]})
            assert flags() == dict.fromkeys(ids, False), "Unarchive cascade profile changed"
            server.call("thread/archive", {"threadId": ids["prior"]})
            assert flags() == original
            assert histories(server) == before
        finally:
            server.close()
        from functools import partial

        from sessions_manager.catalog import Catalog
        from sessions_manager.config import Config
        from sessions_manager.discovery import refresh
        from sessions_manager.models import SourceRoot, identity
        from sessions_manager.native_archive import ArchiveService, NativeClient

        root = SourceRoot.create("codex", home, executable_path=executable, resume_context="native")
        cfg = Config(base / "manager", base / "config", [root], "replace")
        cfg.prepare()
        selector = "s-" + identity(root.namespace_id, ids["parent"])
        with Catalog(cfg.data_dir) as catalog:
            refresh(cfg, catalog)
            service = ArchiveService(cfg, catalog, client_factory=partial(NativeClient, env=env))
            plan = service.preview("archive", selector)
            result = service.commit(
                "archive", selector, plan["confirmation_token"], assert_closed=True
            )
            assert result["state"] == "complete", result.get("error")
            assert flags() == dict(parent=True, child=True, prior=True, neighbor=False)
        with Catalog(cfg.data_dir) as catalog:
            service = ArchiveService(cfg, catalog, client_factory=partial(NativeClient, env=env))
            plan = service.preview("unarchive", selector)
            result = service.commit(
                "unarchive", selector, plan["confirmation_token"], assert_closed=True
            )
            assert result["state"] == "complete", result.get("error")
            assert flags() == original
        if cli is not None:
            import tomli_w

            cfg.config_path.write_text(
                tomli_w.dumps(
                    {
                        "discovery_roots_mode": "replace",
                        "sources": [
                            {
                                "provider": "codex",
                                "path": str(home),
                                "executable": str(executable),
                                "resume_context": "native",
                            }
                        ],
                    }
                )
            )
            args = [
                str(cli),
                "--config",
                str(cfg.config_path),
                "--data-dir",
                str(cfg.data_dir),
                "--format",
                "json",
            ]

            def run(*command):
                result = subprocess.run(
                    [*args, *command],
                    cwd=project,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert result.returncode == 0, "Installed native CLI command failed: " + command[0]
                return json.loads(result.stdout)["data"]

            run("refresh", "--source", "codex")
            run("hide", selector)
            plan = run("archive", selector)
            assert (
                run(
                    "archive", selector, "--confirm", plan["confirmation_token"], "--assert-closed"
                )["state"]
                == "complete"
            )
            assert len(run("archives")["items"]) == 3
            plan = run("unarchive", selector)
            assert (
                run(
                    "unarchive",
                    selector,
                    "--confirm",
                    plan["confirmation_token"],
                    "--assert-closed",
                )["state"]
                == "complete"
            )
            assert flags() == original
            shown = run("show", selector)
            assert shown["session"]["hidden"] and shown["events"]
            run("unhide", selector)
        server = Server(executable, project, env)
        try:
            assert histories(server) == before
        finally:
            server.close()
        return {
            "version": version,
            "installed_cli": cli is not None,
            "manager_coordinator": True,
            "fixture_seeded_graph": True,
            "archive_cascade": True,
            "unarchive_cascade": True,
            "original_flags_restored": True,
            "history_and_ids_preserved": True,
            "neighbor_preserved": True,
            "restart_between_operations": True,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    args = parser.parse_args()
    assert args.executable.is_absolute() and args.executable.is_file()
    print(json.dumps(verify(args.executable)))
