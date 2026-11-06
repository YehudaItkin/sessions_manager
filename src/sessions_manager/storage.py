"""Cached sizes of known native history trees, separate from session attribution."""

import json
import os
import stat

from .models import now_ms


def measure(root):
    from .sources.base import source_directory

    files, visited = {}, set()
    complete, reason = True, None
    nodes = 0

    def visit(fd, name, depth=0):
        nonlocal complete, reason, nodes
        nodes += 1
        if depth > 64 or nodes > 100000:
            complete, reason = False, "storage_enumeration_limit"
            return
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            key = f"{info.st_dev}:{info.st_ino}"
            if stat.S_ISREG(info.st_mode):
                files[key] = {"bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
            elif stat.S_ISDIR(info.st_mode):
                if key in visited:
                    return
                visited.add(key)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    actual = os.fstat(child)
                    if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
                        raise OSError("source directory changed")
                    with os.scandir(child) as entries:
                        for entry in entries:
                            visit(child, entry.name, depth + 1)
                            if nodes > 100000:
                                break
                finally:
                    os.close(child)
            else:
                complete, reason = False, "storage_unsafe_artifact"
        except FileNotFoundError:
            if depth:
                complete, reason = False, "storage_source_changed"
        except OSError:
            complete, reason = False, "storage_unavailable"

    required = set()
    try:
        if not root.path.is_dir():
            raise OSError()
        if root.provider == "codex":
            paths = [root.path / name for name in ("sessions", "archived_sessions")]
            for name in ("state_5.sqlite", "thread_history_1.sqlite"):
                paths.extend(root.path / (name + suffix) for suffix in ("", "-wal", "-shm"))
        elif root.provider == "claude":
            paths = [root.path / "projects"]
        else:
            name = "sessions" if root.provider == "grok" else "chats"
            base = root.path / name
            if base.is_dir():
                paths = [base]
            else:
                # Explicit history-root overrides use the same bounded native shapes.
                from .sources.base import ScanResult, discover_paths

                result = ScanResult()
                marker = "summary.json" if root.provider == "grok" else "store.db"
                paths = [p.parent for p in discover_paths(root.path, "*/*/" + marker, result)]
                required.update(paths)
                complete, reason = result.complete, result.reason
            if root.provider == "grok":
                for name in ("session_search.sqlite", "grok.db"):
                    paths.extend(root.path / (name + suffix) for suffix in ("", "-wal", "-shm"))
        for path in paths:
            try:
                with source_directory(path.parent, root.path) as fd:
                    visit(fd, path.name, 1 if path in required else 0)
            except FileNotFoundError:
                complete, reason = False, "storage_source_changed"
            except OSError:
                complete, reason = False, "storage_unavailable"
    except OSError:
        complete, reason = False, "storage_unavailable"
    return {
        "files": files,
        "complete": complete,
        "reason": reason,
        "as_of": now_ms(),
        "stale": False,
        "known": complete or bool(files),
    }


def publish(db, root_id, observation, *, stale=False):
    previous = db.execute(
        "SELECT payload FROM source_storage WHERE root_id=?", (root_id,)
    ).fetchone()
    if observation is None or stale or not observation["complete"]:
        if previous:
            saved = json.loads(previous[0])
            saved.update(stale=True, complete=False, reason="storage_unavailable")
            observation = saved
        elif observation is None or stale:
            observation = {
                "files": {},
                "complete": False,
                "known": False,
                "as_of": None,
                "stale": True,
                "reason": "storage_unavailable",
            }
    db.execute(
        "INSERT OR REPLACE INTO source_storage VALUES (?,?)", (root_id, json.dumps(observation))
    )


def summarize(catalog, sessions, selection):
    providers = (selection or {}).get("providers")
    if selection is None:
        providers = {s.provider for s in sessions}
    roots, union, conflicts = [], {}, set()
    for row in catalog.connection.execute(
        "SELECT r.root_id,r.payload,r.state,s.payload AS storage FROM roots r LEFT JOIN source_storage s USING(root_id)"
    ):
        root = json.loads(row["payload"])
        if providers and root["provider"] not in providers:
            continue
        observation = json.loads(row["storage"]) if row["storage"] else {}
        files = observation.get("files", {})
        for key, value in files.items():
            if key in union and union[key] != value:
                conflicts.add(key)
            union[key] = value
        complete = bool(observation.get("complete")) and row["state"] == "complete"
        roots.append(
            {
                "root_id": row["root_id"],
                "provider": root["provider"],
                "path": root["path"],
                "value": sum(f["bytes"] for f in files.values())
                if observation.get("known")
                else None,
                "complete": complete,
                "stale": bool(observation.get("stale")) or not complete,
                "as_of": observation.get("as_of"),
                "reason": observation.get("reason"),
                "cached": True,
            }
        )
    known = sum(r["value"] is not None for r in roots)
    return {
        "scope": "whole_catalogued_history_roots",
        "cached": True,
        "value": sum(v["bytes"] for k, v in union.items() if k not in conflicts)
        if (known or not roots) and (not union or len(conflicts) < len(union))
        else None,
        "reason": "storage_observation_conflict"
        if conflicts
        else None
        if all(r["complete"] for r in roots)
        else "storage_unavailable",
        "complete": all(r["complete"] for r in roots) and not conflicts,
        "selected_roots": len(roots),
        "known_roots": known,
        "as_of": min((r["as_of"] for r in roots), default=None)
        if all(r["as_of"] is not None for r in roots)
        else None,
        "deduplicated_files": len(union) - len(conflicts),
        "conflicting_files": len(conflicts),
        "roots": roots,
        "notes": [
            "Whole history roots for the selected sources; session/project/date filters do not divide shared bytes.",
            "Known history trees and native DB/WAL/SHM files, counted once by device/inode. Credentials and manager trash are excluded.",
            "Non-atomic cached size observation, not reclaimable space or a per-session allocation.",
        ],
    }
