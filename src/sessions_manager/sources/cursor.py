import json

from ..models import Capability, Failure, Session, timestamp
from .base import ScanResult, directory_inventory, json_file, read_many, resume_context_verified
from .sqlite_reader import NativeSQLite


class Adapter:
    profile = "cursor-cli-2026.10"

    def __init__(self, root):
        self.root = root
        self._history = {}

    def discover(self):
        result = ScanResult(profile=self.profile)
        if not self.root.path.exists():
            return result
        home = self.root.path / "chats" if (self.root.path / "chats").is_dir() else self.root.path
        for session in read_many(self._discover_one, sorted(home.glob("*/*/store.db"))):
            if session is None:
                result.complete, result.reason = False, "invalid_native_record"
            else:
                result.sessions.append(session)
        return result

    def _discover_one(self, store):
        try:
            meta = json_file(store.parent / "meta.json")
            if meta.get("schemaVersion") != 1:
                raise Failure("unsupported_native_schema", 3)
            with NativeSQLite(store, {"meta": {"key", "value"}, "blobs": {"id", "data"}}) as reader:
                rows = reader.read("meta", ["value"], key="key", value="0")
                if not rows:
                    raise Failure("unsupported_native_schema", 3)
                native_meta = json.loads(bytes.fromhex(rows[0]["value"]).decode())
                from .cursor_wire import graph

                def load(key):
                    found = reader.read("blobs", ["data"], key="id", value=key)
                    return found[0]["data"] if found else None

                if not hasattr(self, "_history"):
                    self._history = {}
                self._history[native_meta.get("agentId")] = graph(
                    native_meta.get("latestRootBlobId"),
                    load,
                    self.root.namespace_id + ":" + str(native_meta.get("agentId")),
                )
            native = native_meta.get("agentId")
            if not isinstance(native, str) or native != store.parent.name:
                raise Failure("unsupported_native_schema", 3)
            inventory, known_bytes = directory_inventory(store.parent)
            session = Session.build(
                self.root,
                native,
                store.parent,
                cwd=meta.get("cwd"),
                title=native_meta.get("name"),
                model=native_meta.get("lastUsedModel"),
                created_at=timestamp(meta.get("createdAtMs") or native_meta.get("createdAt")),
                last_activity_at=timestamp(meta.get("updatedAtMs")),
                profile=self.profile,
                fingerprint=inventory,
                known_bytes=known_bytes,
                extra={"latest_root": native_meta.get("latestRootBlobId")},
            )
            session.capabilities["metadata"] = Capability("supported")
            session.capabilities["usage"] = Capability("unavailable", "not_recorded")
            if resume_context_verified(self.root):
                session.capabilities["resume"] = Capability("supported")
            return session
        except (Failure, OSError, ValueError, UnicodeError):
            return None

    def read_history(self, session):
        if session.native_id in getattr(self, "_history", {}):
            return self._history[session.native_id]
        from pathlib import Path

        from ..models import HistoryResult
        from .cursor_wire import graph

        try:
            with NativeSQLite(
                Path(session.locator) / "store.db", {"blobs": {"id", "data"}}
            ) as reader:

                def load(key):
                    rows = reader.read("blobs", ["data"], key="id", value=key)
                    return rows[0]["data"] if rows else None

                return graph(
                    session.extra.get("latest_root"),
                    load,
                    session.namespace_id + ":" + session.native_id,
                )
        except (Failure, OSError):
            return HistoryResult([], "unavailable", "cursor_history_unavailable")

    def prepare_cleanup_bundle(self, session):
        from .base import prepare_cleanup_bundle

        return prepare_cleanup_bundle(self.root, session)

    def read_usage(self, session):
        from ..models import UsageResult

        return UsageResult(state="unavailable", reason="not_recorded")
