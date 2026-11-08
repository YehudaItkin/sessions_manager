"""Verified positive process evidence; absence and stale records mean unknown."""

import ctypes
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from .models import ActivityEvidence, public


def process_info(pid):
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        if result.returncode:
            return None
        birth = int(dt.datetime.strptime(result.stdout.strip(), "%a %b %d %H:%M:%S %Y").timestamp())
        library = ctypes.CDLL("/usr/lib/libproc.dylib")
        library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        library.proc_pidpath.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(4096)
        if library.proc_pidpath(pid, buffer, len(buffer)) <= 0:
            return None
        return {"pid_start": birth, "executable": str(Path(os.fsdecode(buffer.value)).resolve())}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def verify(record, probe=process_info):
    pid = record.get("pid")
    if (
        type(pid) is not int
        or pid <= 0
        or not record.get("pid_start")
        or not record.get("executable")
    ):
        return "unknown"
    process = probe(pid)
    if not process:
        return "unknown"
    if any(process.get(key) != record.get(key) for key in ("pid_start", "executable")):
        return "unknown"
    if process.get("cwd") is not None and process["cwd"] != record.get("cwd"):
        return "unknown"
    return "active"


def observe(root, sessions, *, probe=None):
    records = []
    try:
        if root.provider == "grok":
            path = root.path / "active_sessions.json"
            if path.exists():
                value = json.loads(path.read_text())
                if isinstance(value, list):
                    records = [r for r in value if isinstance(r, dict)]
        elif root.provider == "claude":
            for path in (root.path / "sessions").glob("*.json"):
                value = json.loads(path.read_text())
                if isinstance(value, dict):
                    records.append(value)
    except (OSError, ValueError):
        pass
    by_id = {}
    for session in sessions:
        by_id.setdefault(session.native_id, []).append(session)
        session.activity = "unknown"
        session.activity_evidence = {}
    if root.executable_path is None:
        return
    for record in records:
        native = record.get("session_id") or record.get("sessionId")
        matching = (
            [s for s in by_id.get(native, []) if record.get("cwd") == s.cwd]
            if isinstance(native, str)
            else []
        )
        if not matching:
            continue
        if type(record.get("pid")) is not int or type(record.get("pid_start")) is not int:
            continue
        expected = {
            "pid": record.get("pid"),
            "pid_start": record.get("pid_start"),
            "cwd": record.get("cwd"),
            "executable": str(root.executable_path.resolve()),
        }
        state = verify(expected, probe or process_info)
        for session in matching:
            if session.activity == "active" and state != "active":
                continue
            session.activity = state
            session.activity_evidence = public(
                ActivityEvidence(
                    session.session_uid,
                    status=state,
                    evidence_kind="native_registry",
                    pid=expected["pid"],
                    process_start_identity=str(expected["pid_start"]),
                    resolved_executable=expected["executable"],
                    confidence="verified",
                )
            )
