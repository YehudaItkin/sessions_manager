import hashlib
import json
from pathlib import Path

from ..models import Capability, Failure, Session, annotate_dates, timestamp
from .base import (
    ScanResult,
    available_root,
    directory_inventory,
    discover_paths,
    json_file,
    read_many,
    resume_capability,
)
from .sqlite_reader import NativeSQLite


class Adapter:
    profile = "cursor-cli-2026.10"

    def __init__(self, root):
        self.root = root
        self._history = {}
        self._workspace_cwds = {}

    def discover(self):
        result = ScanResult(profile=self.profile)
        if not available_root(self.root.path, result):
            return result
        home = self.root.path / "chats" if (self.root.path / "chats").is_dir() else self.root.path
        candidates = {}
        for sidecar in discover_paths(home, "*/*/meta.json", result, boundary=self.root.path):
            try:
                meta = json_file(sidecar)
                cwd = meta.get("cwd")
                workspace = sidecar.parent.parent.name
                if (
                    meta.get("schemaVersion") == 1
                    and isinstance(cwd, str)
                    and Path(cwd).is_absolute()
                    and hashlib.md5(cwd.encode()).hexdigest() == workspace
                ):
                    candidates.setdefault(workspace, set()).add(cwd)
            except (Failure, OSError, ValueError):
                continue
        self._workspace_cwds = {
            key: next(iter(values)) for key, values in candidates.items() if len(values) == 1
        }
        for session in read_many(
            self._discover_one,
            discover_paths(home, "*/*/store.db", result, boundary=self.root.path),
        ):
            if session is None:
                result.complete, result.reason = False, "invalid_native_record"
            else:
                result.sessions.append(session)
        return result

    def _discover_one(self, store):
        try:
            # Bind cached content to the observation before the SQLite snapshot,
            # never a newer WAL stamp taken after a concurrent commit.
            inventory, known_bytes = directory_inventory(store.parent)
            sidecar = store.parent / "meta.json"
            meta = json_file(sidecar) if sidecar.exists() else {}
            if sidecar.exists() and meta.get("schemaVersion") != 1:
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
                if not getattr(self, "metadata_only", False):
                    self._history[str(store.parent)] = graph(
                        native_meta.get("latestRootBlobId"),
                        load,
                        self.root.namespace_id + ":" + str(native_meta.get("agentId")),
                    )
            native = native_meta.get("agentId")
            if not isinstance(native, str) or native != store.parent.name:
                raise Failure("unsupported_native_schema", 3)
            session = Session.build(
                self.root,
                native,
                store.parent,
                cwd=meta.get("cwd") or self._workspace_cwds.get(store.parent.parent.name),
                title=native_meta.get("name"),
                model=native_meta.get("lastUsedModel"),
                created_at=timestamp(meta.get("createdAtMs") or native_meta.get("createdAt")),
                last_activity_at=timestamp(meta.get("updatedAtMs")),
                profile=self.profile,
                fingerprint=inventory,
                known_bytes=known_bytes,
                extra={
                    "latest_root": native_meta.get("latestRootBlobId"),
                    "workspace_id": store.parent.parent.name,
                    "cwd_provenance": "sidecar"
                    if meta.get("cwd")
                    else "workspace_neighbor"
                    if store.parent.parent.name in self._workspace_cwds
                    else "not_recorded",
                },
            )
            annotate_dates(
                session,
                [meta.get("createdAtMs") or native_meta.get("createdAt")],
                [meta.get("updatedAtMs")],
            )
            session.capabilities["metadata"] = Capability("supported")
            session.capabilities["usage"] = Capability("unavailable", "not_recorded")
            session.capabilities["resume"] = resume_capability(self.root)
            return session
        except (Failure, OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def read_history(self, session):
        if session.locator in getattr(self, "_history", {}):
            return self._history[session.locator]
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
        from ..models import ContextMetric, UsageResult
        from .cursor_wire import context_details

        result = UsageResult(state="unavailable", reason="not_recorded")
        if session.profile != self.profile:
            return result
        root_id = session.extra.get("latest_root")
        try:
            with NativeSQLite(
                Path(session.locator) / "store.db", {"blobs": {"id", "data"}}
            ) as reader:
                rows = reader.read("blobs", ["data"], key="id", value=root_id)
                if not rows:
                    return result
                values = context_details(rows[0]["data"])
                if values is not None:
                    result.context_metrics = [
                        ContextMetric(
                            session.session_uid,
                            *values,
                            source_profile=self.profile,
                            native_revision={
                                "root_blob_id": root_id,
                                "source_fingerprint": session.fingerprint,
                            },
                            completeness="partial" if None in values else "complete",
                        )
                    ]
        except (Failure, OSError, ValueError, TypeError):
            result.reason = "cursor_context_unavailable"
        return result
