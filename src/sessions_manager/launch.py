"""Exact native resume. Terminal streams belong to the child, never to logs."""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

from .discovery import adapter
from .models import Failure, LaunchRequest, ManualResumeGuide, public
from .sources.base import fingerprint, resume_context_verified


def root_from_dict(value):
    from .models import SourceRoot

    value = dict(value)
    value["path"] = Path(value["path"])
    if value.get("executable_path"):
        value["executable_path"] = Path(value["executable_path"])
    return SourceRoot(**value)


def catalog_alias_binding(data_dir, uid):
    """Read the current alias guard without creating/migrating manager state."""
    import sqlite3
    import stat
    from contextlib import closing

    from .catalog import session_payload
    from .fsops import trusted_directory

    directory = Path(data_dir)
    if directory.is_symlink():
        raise Failure("unsafe_directory_path", 5)
    if not directory.exists():
        return None
    directory = trusted_directory(directory, private=True)
    path = directory / "catalog.sqlite3"
    if not path.exists():
        return None
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        raise Failure("unsafe_catalog", 6)
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            row = db.execute("SELECT payload,presence FROM sessions WHERE uid=?", (uid,)).fetchone()
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='native_archive_operations'"
            ).fetchone():
                from .models import identity
                from .native_archive import TERMINAL, load_operation

                for saved in db.execute("SELECT payload FROM native_archive_operations"):
                    operation = load_operation(saved[0])
                    namespace = operation["plan"]["binding"]["namespace"]
                    if operation["state"] not in TERMINAL and any(
                        identity(namespace, tid) == uid for tid in operation["plan"]["before"]
                    ):
                        raise Failure("archive_operation_pending", 5)
    except sqlite3.Error:
        raise Failure("catalog_binding_unavailable", 6) from None
    if row is None:
        return None
    session = session_payload(row[0])
    if session.extra.get("identity_conflict"):
        raise Failure(session.extra["identity_conflict"], 5)
    if row[1] != "present":
        raise Failure("source_changed", 5)
    return session.extra.get("alias_bindings", [])


def build_request(root, session, data_dir, *, cwd=None, target="current"):
    binding = catalog_alias_binding(data_dir, session.session_uid)
    alias_bindings = session.extra.get("alias_bindings", []) if binding is None else binding
    chosen = Path(cwd or session.cwd or "/nonexistent").expanduser().absolute()
    locator = {
        "namespace_id": session.namespace_id,
        "native_id": session.native_id,
        "root_id": root.root_id,
        "path": session.locator,
        "original_cwd": session.cwd,
    }

    def unavailable(reason):
        guide = ManualResumeGuide(
            root.provider,
            session.native_id,
            locator,
            session.cwd,
            str(chosen),
            reason,
            [str(root.executable_path), "--help"] if root.executable_path else [],
        )
        raise Failure(reason, 4, data={"manual_resume_guide": public(guide)})

    if session.presence != "present" or session.capabilities["resume"].state != "supported":
        reason = session.capabilities["resume"].reason
        unavailable("resume_binding_unverified" if reason in (None, "not_verified") else reason)
    if (
        not resume_context_verified(root)
        or not session.native_id
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", session.native_id)
    ):
        unavailable("resume_binding_unverified")
    if not chosen.is_dir():
        unavailable("resume_cwd_unavailable")
    from .sources.native_version import resolve_cleanup_version

    relocated_supported = (
        root.provider == "codex"
        and session.extra.get("history_mode") == "paginated"
        and resolve_cleanup_version(root) == "0.166.0"
    )
    if (
        not session.cwd or chosen.resolve() != Path(session.cwd).resolve()
    ) and not relocated_supported:
        unavailable("resume_cwd_unsupported")
    executable = root.executable_path
    if (
        not executable
        or not executable.is_absolute()
        or not executable.is_file()
        or not os.access(executable, os.X_OK)
    ):
        raise Failure("native_executable_unavailable", 8)
    info = executable.resolve().stat()
    if info.st_uid not in (os.getuid(), 0) or info.st_mode & 0o022:
        raise Failure("unsafe_executable", 5)
    args = {
        "codex": ["resume", session.native_id, "-C", str(chosen)],
        "claude": ["--resume", session.native_id],
        "grok": ["--cwd", str(chosen), "--resume", session.native_id],
        "cursor": ["--workspace", str(chosen), "--resume", session.native_id],
    }[root.provider]
    context = {}
    if root.provider in ("codex", "claude"):
        context["CODEX_HOME" if root.provider == "codex" else "CLAUDE_CONFIG_DIR"] = str(root.path)
    return LaunchRequest(
        str(uuid.uuid4()),
        session.session_uid,
        session.fingerprint,
        locator,
        str(executable),
        [str(executable), *args],
        str(chosen),
        context,
        target,
        str(Path(data_dir).absolute()),
        os.getuid(),
        source_root=public(root),
        executable_fingerprint=fingerprint(executable.resolve()),
        alias_bindings=alias_bindings,
    )


def revalidate(request):
    if request.owner_uid != os.getuid():
        raise Failure("launch_owner_mismatch", 5)
    if fingerprint(Path(request.executable).resolve()) != request.executable_fingerprint:
        raise Failure("executable_changed", 5)
    binding = catalog_alias_binding(request.data_dir, request.session_uid)
    if binding is not None and binding != request.alias_bindings:
        raise Failure("launch_binding_changed", 5)
    for alias in request.alias_bindings:
        peer = root_from_dict(alias["root"])
        discovered = adapter(peer).discover()
        copies = [s for s in discovered.sessions if s.session_uid == request.session_uid]
        if (
            not discovered.complete
            or len(copies) != 1
            or copies[0].fingerprint != alias["fingerprint"]
            or copies[0].locator != alias["locator"]
        ):
            raise Failure("identity_binding_unverified", 5)
    root = root_from_dict(request.source_root)
    sessions = adapter(root).discover().sessions
    found = [s for s in sessions if s.session_uid == request.session_uid]
    if len(found) != 1 or found[0].fingerprint != request.source_fingerprint:
        raise Failure("source_changed", 5)
    rebuilt = build_request(
        root, found[0], request.data_dir, cwd=request.cwd, target=request.target
    )
    if (
        rebuilt.argv != request.argv
        or rebuilt.history_locator != request.history_locator
        or rebuilt.context_overrides != request.context_overrides
    ):
        raise Failure("launch_binding_changed", 5)
    return root


def launch_current(request, *, output_to_stderr=False):
    revalidate(request)
    try:
        import sys

        result = subprocess.run(
            request.argv,
            stdout=sys.stderr if output_to_stderr else None,
            cwd=request.cwd,
            env={**os.environ, **request.context_overrides},
            shell=False,
            check=False,
        )
    except OSError:
        raise Failure("native_exec_failed", 8) from None
    except KeyboardInterrupt:
        code = 130
    else:
        code = result.returncode
    return {
        "launch_id": request.launch_id,
        "state": "child_exited",
        "child_exit_code": code,
        "message": "Native CLI interrupted (130)."
        if code == 130
        else f"Native CLI exited with code {code}."
        if code
        else "Native CLI exited successfully.",
    }
