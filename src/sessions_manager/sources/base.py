from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from ..models import Capability, Failure, now_ms

RECORD_ERRORS = (Failure, OSError, ValueError, TypeError, KeyError, AttributeError)


@dataclass
class SourceProfile:
    name: str
    required_fields: set[str]
    capabilities: dict = field(default_factory=dict)

    def accepts(self, fields):
        return self.required_fields <= set(fields)

    def capability(self, name):
        return self.capabilities.get(name, Capability("unavailable", "not_verified"))


@dataclass
class ScanResult:
    sessions: list = field(default_factory=list)
    complete: bool = True
    reason: str | None = None
    profile: str | None = None
    stage: str = "complete"
    started_at: int = field(default_factory=now_ms)
    finished_at: int | None = None
    source_revision_range: list = field(default_factory=list)


def read_many(reader, paths):
    """Bound independent file opens; each native DB connection stays in its reader thread."""
    from concurrent.futures import ThreadPoolExecutor

    def isolated(path):
        try:
            return reader(path)
        except RECORD_ERRORS:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        yield from pool.map(isolated, paths)


def fingerprint(path: Path):
    try:
        info = path.stat(follow_symlinks=False)
        value = {
            "dev": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
        }
        if stat.S_ISLNK(info.st_mode):
            target = path.stat()
            value["target"] = {
                "dev": target.st_dev,
                "inode": target.st_ino,
                "size": target.st_size,
                "mtime_ns": target.st_mtime_ns,
            }
        return value
    except OSError:
        return {}


def json_file(path: Path):
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise Failure("invalid_native_record", 3) from None


def json_lines(path: Path, *, cache=None):
    if cache is not None:
        yield from cache.read(path)
        return
    # Native messages can be hundreds of KiB. Read complete byte lines with a
    # bounded buffer, then decode UTF-8 strictly rather than many tiny text reads.
    with path.open("rb", buffering=262144) as stream:
        for ordinal, raw_line in enumerate(stream):
            line = raw_line.decode("utf-8")
            if line.strip():
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError()
                    yield ordinal, value
                except ValueError:
                    raise Failure("invalid_native_record", 3) from None


def directory_inventory(path):
    import os
    import stat

    inventory = {}
    complete = True
    with os.scandir(path) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                complete = False
                continue
            inventory[entry.name] = {
                "dev": info.st_dev,
                "inode": info.st_ino,
                "size": info.st_size,
                "mtime_ns": info.st_mtime_ns,
            }
    return inventory, sum(i["size"] for i in inventory.values()) if complete else None


def claude_cleanup_shape(rows, native_id):
    for row in rows:
        if row.get("type") not in ("user", "assistant"):
            continue
        patch = re.fullmatch(r"2\.1\.([0-9]+)", str(row.get("version", "")))
        message = row.get("message")
        if (
            not patch
            or int(patch.group(1)) > 299
            or row.get("sessionId", row.get("session_id")) != native_id
            or not isinstance(row.get("uuid"), str)
            or not isinstance(message, dict)
            or message.get("role") not in ("user", "assistant")
            or not isinstance(message.get("content"), (str, list))
        ):
            return False
    return True


def claude_workflows(path):
    """Only closed per-session run records and their local script copies; never execute JS."""
    if path.is_symlink() or not path.is_dir():
        raise Failure("unknown_bundle_topology", 4)
    runs, scripts, referenced_scripts = set(), set(), set()
    for entry in path.iterdir():
        if entry.name == "scripts" and not entry.is_symlink() and entry.is_dir():
            for script in entry.iterdir():
                if script.is_symlink() or not script.is_file() or script.suffix != ".js":
                    raise Failure("unknown_bundle_topology", 4)
                scripts.add(script)
            continue
        if entry.is_symlink() or not entry.is_file() or entry.suffix not in (".json", ".js"):
            raise Failure("unknown_bundle_topology", 4)
        if entry.suffix == ".js":
            scripts.add(entry)
            continue
        row = json_file(entry)
        if row.get("runId") != entry.stem or not isinstance(row.get("phases"), list):
            raise Failure("unknown_bundle_topology", 4)
        if row.get("status") not in ("completed", "failed", "stopped", "interrupted", "cancelled"):
            raise Failure("workflow_not_closed", 5)
        runs.add(entry.stem)
        script_path = row.get("scriptPath")
        if isinstance(script_path, str):
            candidate = Path(script_path)
            # Compare the path as data; never follow a reference outside this bundle.
            if candidate.parent in (path, path / "scripts") and candidate.suffix == ".js":
                referenced_scripts.add(candidate)
    identified_scripts = {
        script for script in scripts if script.parent == path and script.stem in runs
    }
    if not scripts <= identified_scripts | referenced_scripts:
        raise Failure("unknown_bundle_topology", 4)


def prepare_cleanup_bundle(root, session, *, common_checks=None):
    from ..models import CleanupBundle

    expected = {
        "claude": ("claude-jsonl-2.1", "2.1.299"),
        "grok": ("grok-build-1.0.70", "1.0.70"),
        "cursor": ("cursor-cli-2026.10", "2026.10.22-27dcf5f"),
    }
    if root.provider == "codex":
        raise Failure("native_cascade_unbounded", 4)
    profile, version = expected[root.provider]
    from .native_version import resolve_cleanup_version

    if session.profile != profile or resolve_cleanup_version(root) not in (version, "synthetic"):
        raise Failure("cleanup_profile_unverified", 4)
    if session.capabilities["cleanup"].state == "unsafe":
        raise Failure(session.capabilities["cleanup"].reason or "unsafe_bundle", 5)
    path = Path(session.locator)
    if root.provider == "claude":
        relative = path.relative_to(root.path)
        if (
            len(relative.parts) != 3
            or relative.parts[0] != "projects"
            or path.name != session.native_id + ".jsonl"
        ):
            raise Failure("unknown_bundle_topology", 4)
        artifacts = [path]
        companion = path.with_suffix("")
        if companion.exists():
            if any(
                p.name not in {"subagents", "tool-results", "workflows"}
                for p in companion.iterdir()
            ):
                raise Failure("unknown_bundle_topology", 4)
            if (companion / "workflows").exists() or (companion / "workflows").is_symlink():
                claude_workflows(companion / "workflows")
            artifacts.append(companion)
        verified = (
            getattr(session, "_cleanup_shape_verified", None) if common_checks is not None else None
        )
        # Discovery already parsed these rows. Mutating operations always read them afresh.
        if verified is None:
            verified = claude_cleanup_shape((row for _, row in json_lines(path)), session.native_id)
        if not verified:
            raise Failure("cleanup_profile_unverified", 4)
    elif root.provider == "grok":
        home = root.path / "sessions" if (root.path / "sessions").exists() else root.path

        def checked(key, probe):
            # Only discovery supplies this per-scan cache. Mutation always probes afresh.
            if common_checks is None:
                return probe()
            if key not in common_checks:
                common_checks[key] = probe()
            return common_checks[key]

        if checked(
            (home, "shared_files"), lambda: any(not p.is_dir() for p in home.iterdir())
        ) or checked(
            (path.parent, "shared_files"), lambda: any(p.is_file() for p in path.parent.iterdir())
        ):
            raise Failure("shared_dependency_unverified", 4)
        if checked(
            (root.path, "shared_indices"),
            lambda: any(
                (root.path / name).exists()
                for name in (
                    "grok.db",
                    "grok.db-wal",
                    "grok.db-shm",
                    "session_search.sqlite",
                    "session_search.sqlite-wal",
                    "session_search.sqlite-shm",
                    "search.db",
                    "session-index.db",
                    "relocations.json",
                    "search",
                )
            ),
        ):
            raise Failure("shared_dependency_unverified", 4)
        allowed = {
            "summary.json",
            "updates.jsonl",
            "chat_history.jsonl",
            "usage.json",
            "signals.json",
            "images",
            "snapshots",
            "logs",
        }
        if any(p.name not in allowed for p in path.iterdir()):
            raise Failure("unknown_bundle_topology", 4)
        info = json_file(path / "summary.json").get("info", {})
        if info.get("parent_session_id") or info.get("child_session_ids"):
            raise Failure("shared_dependency_unverified", 4)
        artifacts = [path]
    else:
        if path.name != session.native_id or not (path / "store.db").is_file():
            raise Failure("unknown_bundle_topology", 4)
        allowed = {
            "meta.json",
            "store.db",
            "store.db-wal",
            "store.db-shm",
            "history.jsonl",
            "prompt_history.json",
            "attachments",
            "logs",
        }
        if any(p.name not in allowed for p in path.iterdir()):
            raise Failure("unknown_bundle_topology", 4)
        if session.history_state not in ("complete", "partial"):
            raise Failure("cleanup_codec_unverified", 4)
        artifacts = [path]
    return CleanupBundle(session.session_uid, profile, root.root_id, artifacts)


def usage_counts(raw, mapping, *, claude=False):
    from ..models import counter

    result = {key: counter(raw.get(native)) for key, native in mapping.items()}
    if claude:
        parts = [
            result.get(key) for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens")
        ]
        result["input_tokens"] = sum(parts) if all(v is not None for v in parts) else None
    if result.get("input_tokens") is not None and result.get("output_tokens") is not None:
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


def resume_context_verified(root):
    if root.resume_context != "native" or root.executable_path is None:
        return False
    if (
        not root.executable_path.is_absolute()
        or not root.executable_path.is_file()
        or not os.access(root.executable_path, os.X_OK)
    ):
        return False
    if root.provider in ("grok", "cursor") and root.root_kind == "explicit":
        home = Path.home() / (".grok" if root.provider == "grok" else ".cursor")
        child = "sessions" if root.provider == "grok" else "chats"
        return root.path.resolve() in (home.resolve(), (home / child).resolve())
    return True


def resume_capability(root):
    if resume_context_verified(root):
        return Capability("supported")
    executable = root.executable_path
    missing = not executable or not executable.is_file() or not os.access(executable, os.X_OK)
    return Capability(
        "unavailable", "native_executable_unavailable" if missing else "resume_binding_unverified"
    )
