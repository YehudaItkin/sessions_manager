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


def build_request(root, session, data_dir, *, cwd=None, target="current"):
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
    )


def revalidate(request):
    if request.owner_uid != os.getuid():
        raise Failure("launch_owner_mismatch", 5)
    if fingerprint(Path(request.executable).resolve()) != request.executable_fingerprint:
        raise Failure("executable_changed", 5)
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
