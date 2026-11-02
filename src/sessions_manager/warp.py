"""Warp Tab Config transport; only an opaque single-use ticket enters a shell."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import tomli_w

from .config import ensure_private, private_file
from .launch import launch_current, revalidate
from .models import Failure, LaunchRequest, now_ms, public


def schema(catalog):
    catalog.connection.execute("""CREATE TABLE IF NOT EXISTS launches(
      launch_id TEXT PRIMARY KEY,ticket_digest TEXT UNIQUE,payload_digest TEXT,owner_uid INTEGER,
      expires_at INTEGER,state TEXT,config_path TEXT)""")
    catalog.connection.commit()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def create_ticket(catalog, request):
    schema(catalog)
    cleanup_expired(catalog)
    ensure_private(catalog.data_dir / "launches")
    if Path(request.data_dir) != catalog.data_dir:
        raise Failure("launch_data_dir_mismatch", 5)
    token = secrets.token_hex(32)
    raw = json.dumps(public(request), ensure_ascii=False, sort_keys=True).encode()
    path = catalog.data_dir / "launches" / (request.launch_id + ".json")
    private_file(path, raw)
    with catalog.writer() as db:
        db.execute(
            "INSERT INTO launches VALUES (?,?,?,?,?,?,?)",
            (
                request.launch_id,
                digest(token.encode()),
                digest(raw),
                os.getuid(),
                request.expires_at,
                "requested",
                None,
            ),
        )
    return token


def claim_ticket(catalog, token):
    schema(catalog)
    if not re.fullmatch("[a-f0-9]{64}", token):
        raise Failure("invalid_launch_ticket", 8)
    with catalog.writer() as db:
        row = db.execute(
            "SELECT * FROM launches WHERE ticket_digest=?", (digest(token.encode()),)
        ).fetchone()
        if not row:
            raise Failure("invalid_launch_ticket", 8)
        if row["state"] != "requested":
            raise Failure("launch_ticket_replayed", 8)
        if row["expires_at"] < now_ms():
            db.execute("UPDATE launches SET state='expired' WHERE launch_id=?", (row["launch_id"],))
            # Raising rolls back; expiry is still enforced on every subsequent attempt.
            raise Failure("launch_ticket_expired", 8)
        path = catalog.data_dir / "launches" / (row["launch_id"] + ".json")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                ):
                    raise Failure("unsafe_launch_manifest", 5)
                raw = stream.read(1024 * 1024 + 1)
            if digest(raw) != row["payload_digest"] or len(raw) > 1024 * 1024:
                raise Failure("launch_manifest_changed", 5)
            request = LaunchRequest(**json.loads(raw))
        except (OSError, ValueError, TypeError):
            raise Failure("launch_manifest_changed", 5) from None
        if (
            row["owner_uid"] != os.getuid()
            or request.owner_uid != os.getuid()
            or Path(request.data_dir) != catalog.data_dir
        ):
            raise Failure("launch_owner_mismatch", 5)
        updated = db.execute(
            "UPDATE launches SET state='claimed' WHERE launch_id=? AND state='requested' AND expires_at>=?",
            (row["launch_id"], now_ms()),
        )
        if updated.rowcount != 1:
            raise Failure("launch_ticket_replayed", 8)
    return request


def config_text(interpreter, data_dir, token):
    values = [str(interpreter), str(data_dir)]
    if any("{{" in value or "}}" in value for value in values) or not re.fullmatch(
        "[a-f0-9]{64}", token
    ):
        raise Failure("unsafe_warp_launcher_path", 5)
    command = shlex.join(
        [str(interpreter), "-m", "sessions_manager", "--data-dir", str(data_dir), "_launch", token]
    )
    return tomli_w.dumps(
        {
            "name": "Sessions Manager",
            "title": "Sessions Manager",
            "panes": [
                {
                    "id": "terminal",
                    "type": "terminal",
                    "directory": "/",
                    "shell": "zsh",
                    "commands": [command],
                }
            ],
        }
    )


def deliver(catalog, request, *, config_dir=None, opener=subprocess.run):
    revalidate(request)
    if not Path("/bin/zsh").is_file():
        raise Failure("warp_shell_unavailable", 8)
    if config_dir is None and not (
        Path("/Applications/Warp.app").exists() or (Path.home() / "Applications/Warp.app").exists()
    ):
        raise Failure("warp_unavailable", 8)
    directory = Path(config_dir or Path.home() / ".warp/tab_configs")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise Failure("unsafe_warp_config_dir", 5)
    token = create_ticket(catalog, request)
    name = "sessions_manager_" + request.launch_id.replace("-", "")
    path = directory / (name + ".toml")
    private_file(
        path, config_text(Path(sys.executable).absolute(), catalog.data_dir, token).encode()
    )
    with catalog.writer() as db:
        db.execute(
            "UPDATE launches SET config_path=? WHERE launch_id=?", (str(path), request.launch_id)
        )
    try:
        result = opener(
            ["/usr/bin/open", "warp://tab_config/" + name],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is None or result.returncode:
        with catalog.writer() as db:
            db.execute(
                "UPDATE launches SET state='delivery_failed' WHERE launch_id=?",
                (request.launch_id,),
            )
        raise Failure("warp_delivery_failed", 8)
    return {
        "launch_id": request.launch_id,
        "state": "delivered",
        "expires_at": request.expires_at,
        "conversation_loaded": None,
    }


def execute_ticket(catalog, token):
    request = claim_ticket(catalog, token)
    with catalog.writer() as db:
        db.execute(
            "UPDATE launches SET state='handoff_attempted' WHERE launch_id=?", (request.launch_id,)
        )
    try:
        result = launch_current(request)
    except Failure:
        with catalog.writer() as db:
            db.execute(
                "UPDATE launches SET state='exec_failed' WHERE launch_id=?", (request.launch_id,)
            )
        raise
    else:
        with catalog.writer() as db:
            db.execute(
                "UPDATE launches SET state='child_exited' WHERE launch_id=?", (request.launch_id,)
            )
        return result
    finally:
        cleanup_artifacts(catalog, request.launch_id)


def cleanup_artifacts(catalog, launch_id):
    row = catalog.connection.execute(
        "SELECT * FROM launches WHERE launch_id=?", (launch_id,)
    ).fetchone()
    if not row or (
        row["state"] in ("requested", "claimed", "handoff_attempted")
        and row["expires_at"] >= now_ms()
    ):
        return
    paths = [catalog.data_dir / "launches" / (launch_id + ".json")]
    if row["config_path"]:
        candidate = Path(row["config_path"])
        if candidate.name == "sessions_manager_" + launch_id.replace("-", "") + ".toml":
            paths.append(candidate)
    for path in paths:
        try:
            info = path.lstat()
            if (
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and not info.st_mode & 0o077
            ):
                path.unlink()
        except FileNotFoundError:
            pass


def cleanup_expired(catalog):
    if not catalog.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='launches'"
    ).fetchone():
        return
    rows = list(
        catalog.connection.execute(
            "SELECT launch_id,state FROM launches WHERE expires_at<?", (now_ms(),)
        )
    )
    for row in rows:
        if row["state"] == "requested":
            with catalog.writer() as db:
                db.execute(
                    "UPDATE launches SET state='expired' WHERE launch_id=? AND state='requested'",
                    (row["launch_id"],),
                )
        if row["state"] not in ("claimed", "handoff_attempted"):
            cleanup_artifacts(catalog, row["launch_id"])
