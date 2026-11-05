"""Exact recoverable local cleanup. A journal never pretends to be a filesystem transaction."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import fsops
from .config import ensure_private, private_file
from .discovery import adapter
from .models import Failure, TrashEntry, now_ms, public

SCHEMA = """
CREATE TABLE IF NOT EXISTS operation_plans(plan_id TEXT PRIMARY KEY,action TEXT,ids TEXT,payload TEXT,token_digest TEXT UNIQUE,expires_at INTEGER,operation_id TEXT);
CREATE TABLE IF NOT EXISTS operations(operation_id TEXT PRIMARY KEY,plan_id TEXT UNIQUE,state TEXT,created_at INTEGER);
CREATE TABLE IF NOT EXISTS operation_items(operation_id TEXT REFERENCES operations(operation_id),target_id TEXT,payload TEXT,PRIMARY KEY(operation_id,target_id));
CREATE TABLE IF NOT EXISTS trash_entries(trash_id TEXT PRIMARY KEY,session_uid TEXT,operation_id TEXT,payload TEXT,manifest_digest TEXT,state TEXT);
"""


def digest(value):
    return hashlib.sha256(value).hexdigest()


class CleanupService:
    def __init__(self, config, catalog, *, fault=None):
        self.config, self.catalog, self.fault = config, catalog, fault
        self.catalog.connection.executescript(SCHEMA)
        ensure_private(config.data_dir / "trash")
        # Legacy catalogues have no explicit owner. Bind only an unambiguous
        # active trash entry; multiple generations remain protected.
        with catalog.writer() as db:
            db.execute("""UPDATE sessions SET current_trash_id=(
                SELECT trash_id FROM trash_entries WHERE session_uid=sessions.uid
                AND state IN ('trashed','purging'))
                WHERE presence='trashed' AND current_trash_id IS NULL
                AND (SELECT COUNT(*) FROM trash_entries WHERE session_uid=sessions.uid
                AND state IN ('trashed','purging'))=1""")

    @contextmanager
    def lock(self):
        path = self.config.data_dir / "operation.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Failure("unsafe_operation_lock", 6)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _checkpoint(self, stage, target):
        if self.fault:
            self.fault(stage, target)

    def _root(self, root_id):
        root = next((r for r in self.config.roots if r.root_id == root_id and r.enabled), None)
        if root is None:
            raise Failure("source_root_unavailable", 5)
        from .sources.native_version import resolve_cleanup_version

        resolve_cleanup_version(root)
        return root

    def _ids(self, action, ids):
        if action not in ("trash", "restore", "purge") or not ids:
            raise Failure("invalid_operation", 2)
        if action == "trash":
            normalized = [self.catalog.get(value).display_id for value in ids]
        else:
            import re

            if any(not re.fullmatch(r"t-[a-f0-9-]{36}", value) for value in ids):
                raise Failure("invalid_trash_id", 2)
            normalized = list(ids)
        if len(set(normalized)) != len(normalized):
            raise Failure("duplicate_operation_target", 2)
        return normalized

    def _snapshot(self, session):
        if len(session.extra.get("identity_signatures", {})) > 1:
            raise Failure(
                session.extra.get("identity_conflict") or "multiple_locations_unverified", 4
            )
        if session.activity == "active":
            raise Failure("session_active", 5)
        if session.presence != "present":
            raise Failure("source_not_present", 5)
        root = self._root(session.root_id)
        fresh = next(
            (s for s in adapter(root).discover().sessions if s.session_uid == session.session_uid),
            None,
        )
        if fresh is None:
            raise Failure("source_changed", 5)
        from .activity import observe

        observe(root, [fresh])
        if fresh.activity == "active":
            raise Failure("session_active", 5)
        fresh.history_state = session.history_state
        bundle = adapter(root).prepare_cleanup_bundle(fresh)
        artifacts = []
        for path in bundle.artifacts:
            fsops.secure_path(path, root.path)
            if not fsops.same_device(path, self.config.data_dir / "trash"):
                raise Failure("cross_device_unavailable", 4)
            contents = fsops.inventory(path, root.path)
            artifacts.append({"source": str(path), "inventory": contents})
        self._closed_handles(artifacts)
        return {
            "target_id": session.display_id,
            "session_uid": session.session_uid,
            "provider": session.provider,
            "native_id": session.native_id,
            "root": public(root),
            "profile": bundle.profile,
            "activity": session.activity,
            "cwd": session.cwd,
            "artifacts": artifacts,
        }

    def _closed_handles(self, artifacts, *, location=None):
        files = []
        for index, artifact in enumerate(artifacts):
            base = Path(artifact["source"]) if location is None else Path(location) / str(index)
            if not base.exists():
                continue
            for name, row in artifact["inventory"].items():
                if row["kind"] == "file":
                    candidate = base if name == "." else base / name
                    if candidate.exists():
                        files.append(candidate)
        if files and fsops.open_handles(files):
            raise Failure("observed_open_handle", 5)

    def _entry(self, trash_id):
        row = self.catalog.connection.execute(
            "SELECT * FROM trash_entries WHERE trash_id=?", (trash_id,)
        ).fetchone()
        if not row:
            raise Failure("trash_not_found", 2)
        entry = json.loads(row["payload"])
        TrashEntry(**entry)
        if entry["owner_uid"] != os.getuid():
            raise Failure("trash_owner_mismatch", 5)
        directory = self.config.data_dir / "trash" / trash_id
        if row["state"] != "purged":
            fsops.secure_path(directory, self.config.data_dir / "trash")
            manifest = directory / "manifest.json"
            if manifest.is_symlink() or digest(manifest.read_bytes()) != row["manifest_digest"]:
                raise Failure("trash_manifest_changed", 5)
        entry["state"] = row["state"]
        return entry, directory

    def _validate_entry(self, entry, directory, *, subset=False):
        allowed = {"manifest.json", "backup", "payload"}
        if any(p.name not in allowed for p in directory.iterdir()):
            raise Failure("unknown_trash_artifact", 5)
        for category in ("backup", "payload"):
            parent = directory / category
            if not parent.exists():
                continue
            fsops.secure_path(parent, directory)
            if any(
                p.name not in {str(i) for i in range(len(entry["artifacts"]))}
                for p in parent.iterdir()
            ):
                raise Failure("unknown_trash_artifact", 5)
            for index, artifact in enumerate(entry["artifacts"]):
                path = parent / str(index)
                if path.exists() and not fsops.matches(path, artifact["inventory"], subset=subset):
                    raise Failure("trash_payload_changed", 5)

    def preview(self, action, ids):
        ids = self._ids(action, ids)
        targets = []
        for target in ids:
            if action == "trash":
                snapshot = self._snapshot(self.catalog.get(target))
            else:
                entry, directory = self._entry(target)
                if entry["state"] == "purged":
                    raise Failure("trash_already_purged", 4)
                self._validate_entry(entry, directory)
                if action == "restore":
                    root = self._root(entry["source_root"]["root_id"])
                    if (
                        root.namespace_id != entry["source_root"]["namespace_id"]
                        or str(root.path) != entry["source_root"]["path"]
                        or root.executable_version != entry["source_root"].get("executable_version")
                    ):
                        raise Failure("restore_profile_changed", 5)
                    for artifact in entry["artifacts"]:
                        destination = Path(artifact["source"])
                        fsops.secure_path(destination.parent, root.path)
                        if destination.exists() or destination.is_symlink():
                            raise Failure("destination_conflict", 5)
                snapshot = {
                    "target_id": target,
                    "session_uid": entry["session_uid"],
                    "provider": entry["source_root"]["provider"],
                    "profile": entry["source_profile"],
                    "artifacts": entry["artifacts"],
                    "activity": "unknown",
                    "entry_digest": digest(json.dumps(entry, sort_keys=True).encode()),
                }
            targets.append(snapshot)
        token = secrets.token_hex(32)
        plan_id = str(uuid.uuid4())
        expires = now_ms() + 300000
        with self.catalog.writer() as db:
            db.execute(
                "INSERT INTO operation_plans VALUES (?,?,?,?,?,?,NULL)",
                (
                    plan_id,
                    action,
                    json.dumps(ids),
                    json.dumps(targets),
                    digest(token.encode()),
                    expires,
                ),
            )
        size = sum(
            record.get("size", 0)
            for target in targets
            for artifact in target["artifacts"]
            for record in artifact["inventory"].values()
        )
        if action == "purge":
            size = sum(
                record.get("size", 0)
                for target in ids
                for record in fsops.inventory(
                    self.config.data_dir / "trash" / target, self.config.data_dir / "trash"
                ).values()
            )
        visible = [
            {k: v for k, v in target.items() if k not in ("root", "entry_digest", "artifacts")}
            | {"artifacts": [a["source"] for a in target["artifacts"]]}
            for target in targets
        ]
        return {
            "plan_id": plan_id,
            "action": action,
            "targets": visible,
            "known_bytes": size,
            "bytes_complete": True,
            "confirmation_token": token,
            "expires_at": expires,
            "effect": "Irreversibly remove only this manager trash entry"
            if action == "purge"
            else "Recover exact native files without overwriting"
            if action == "restore"
            else "Move exact local history into recoverable manager trash; cloud copies remain",
            "requires_assert_closed": action == "trash"
            and any(t["activity"] == "unknown" for t in targets),
        }

    def _load_plan(self, action, ids, token, assert_closed, operation_id=None):
        if operation_id:
            row = self.catalog.connection.execute(
                "SELECT * FROM operation_plans WHERE operation_id=?", (operation_id,)
            ).fetchone()
        else:
            row = self.catalog.connection.execute(
                "SELECT * FROM operation_plans WHERE token_digest=?", (digest(token.encode()),)
            ).fetchone()
        if row is None or row["action"] != action or json.loads(row["ids"]) != ids:
            raise Failure("confirmation_mismatch", 7)
        targets = json.loads(row["payload"])
        if not row["operation_id"] and row["expires_at"] < now_ms():
            raise Failure("confirmation_expired", 7)
        if (
            action == "trash"
            and any(t["activity"] == "unknown" for t in targets)
            and not assert_closed
        ):
            raise Failure("closed_assertion_required", 7)
        if row["operation_id"]:
            return row["operation_id"], targets
        if action in ("restore", "purge"):
            for target in targets:
                entry, _ = self._entry(target["target_id"])
                if digest(json.dumps(entry, sort_keys=True).encode()) != target["entry_digest"]:
                    raise Failure("confirmation_stale", 7)
        operation_id = str(uuid.uuid4())
        with self.catalog.writer() as db:
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?)",
                (operation_id, row["plan_id"], "running", now_ms()),
            )
            db.execute(
                "UPDATE operation_plans SET operation_id=? WHERE plan_id=? AND operation_id IS NULL",
                (operation_id, row["plan_id"]),
            )
            for target in ids:
                item = {
                    "target_id": target,
                    "state": "preview",
                    "trash_id": None,
                    "error": None,
                    "recovery_options": [],
                }
                self._save_item(operation_id, item, db=db)
        return operation_id, targets

    def _save_item(self, op, item, db=None):
        if db is None:
            with self.catalog.writer() as writer:
                self._save_item(op, item, db=writer)
        else:
            db.execute(
                "INSERT INTO operation_items VALUES (?,?,?) ON CONFLICT(operation_id,target_id) DO UPDATE SET payload=excluded.payload",
                (op, item["target_id"], json.dumps(item)),
            )

    def _entry_state(self, trash_id, state):
        with self.catalog.writer() as db:
            db.execute("UPDATE trash_entries SET state=? WHERE trash_id=?", (state, trash_id))

    def _begin_entry(self, op, target, item):
        if item["trash_id"]:
            return self._entry(item["trash_id"])
        trash_id = "t-" + str(uuid.uuid4())
        directory = ensure_private(self.config.data_dir / "trash" / trash_id)
        ensure_private(directory / "backup")
        ensure_private(directory / "payload")
        entry = TrashEntry(
            trash_id,
            target["session_uid"],
            op,
            target["root"],
            target["profile"],
            os.getuid(),
            target["artifacts"],
        )
        raw = json.dumps(public(entry), ensure_ascii=False, sort_keys=True).encode()
        private_file(directory / "manifest.json", raw)
        fsops.fsync_dir(directory)
        item["trash_id"] = trash_id
        with self.catalog.writer() as db:
            db.execute(
                "INSERT INTO trash_entries VALUES (?,?,?,?,?,?)",
                (
                    trash_id,
                    entry.session_uid,
                    op,
                    json.dumps(public(entry)),
                    digest(raw),
                    "preview",
                ),
            )
            self._save_item(op, item, db=db)
        return public(entry), directory

    def _assert_current_bundle(self, target):
        current = self._snapshot(self.catalog.get(target["target_id"]))
        fields = ("session_uid", "provider", "native_id", "profile", "artifacts")
        root_fields = ("root_id", "namespace_id", "path", "executable_path", "executable_version")
        if any(current.get(key) != target.get(key) for key in fields) or any(
            current["root"].get(key) != target["root"].get(key) for key in root_fields
        ):
            raise Failure("source_changed", 5)

    def _trash(self, op, target, item):
        # Once a rename occurred the original bundle is intentionally incomplete;
        # retries must reconcile its verified journal/payload rather than rediscover it.
        moved_before = False
        if item["trash_id"]:
            payload = self.config.data_dir / "trash" / item["trash_id"] / "payload"
            moved_before = payload.exists() and any(payload.iterdir())
        if not moved_before:
            self._assert_current_bundle(target)
        entry, directory = self._begin_entry(op, target, item)
        artifacts = entry["artifacts"]
        payload = directory / "payload"
        backup = directory / "backup"
        self._validate_entry(entry, directory, subset=True)
        needed = sum(r.get("size", 0) for a in artifacts for r in a["inventory"].values())
        fsops.check_space(directory, needed)
        # An existing verified payload proves an earlier rename even if the journal lagged.
        for index, artifact in enumerate(artifacts):
            source = Path(artifact["source"])
            moved = payload / str(index)
            copy = backup / str(index)
            root = self._root(entry["source_root"]["root_id"])
            if root.namespace_id != entry["source_root"][
                "namespace_id"
            ] or root.executable_version != entry["source_root"].get("executable_version"):
                raise Failure("cleanup_profile_changed", 5)
            if moved.exists():
                if source.exists() or not fsops.matches(moved, artifact["inventory"]):
                    raise Failure("recovery_location_conflict", 5)
                if not copy.exists() or not fsops.matches(copy, artifact["inventory"]):
                    raise Failure("backup_incomplete", 6)
                continue
            fsops.secure_path(source, root.path)
            if not fsops.matches(source, artifact["inventory"], fingerprints=True):
                raise Failure("source_changed", 5)
            fsops.verified_copy(
                source,
                copy,
                artifact["inventory"],
                fault=lambda stage: self._checkpoint(stage, item["target_id"]),
            )
        self._entry_state(entry["trash_id"], "backup_ready")
        item["state"] = "backup_ready"
        self._save_item(op, item)
        self._checkpoint("backup_verified", item["target_id"])
        from .activity import observe
        from .models import Session

        root = self._root(entry["source_root"]["root_id"])
        live = Session.build(
            root, target.get("native_id"), artifacts[0]["source"], cwd=target.get("cwd")
        )
        observe(root, [live])
        if live.activity == "active":
            raise Failure("session_active", 5)
        self._closed_handles(artifacts)
        for index, artifact in enumerate(artifacts):
            source = Path(artifact["source"])
            destination = payload / str(index)
            if destination.exists() and not source.exists():
                continue
            if not fsops.matches(source, artifact["inventory"], fingerprints=True):
                raise Failure("source_changed", 5)
            self._entry_state(entry["trash_id"], "removing")
            self._checkpoint("before_rename", item["target_id"])
            if not moved_before:
                self._assert_current_bundle(target)
            fsops.move_noreplace(source, destination)
            moved_before = True
            self._checkpoint("after_rename", item["target_id"])
            item["state"] = "removing"
            item.setdefault("moved_artifacts", []).append(index)
            self._save_item(op, item)
            self._checkpoint("journal_move", item["target_id"])
        for index, artifact in enumerate(artifacts):
            moved = payload / str(index)
            if Path(artifact["source"]).exists() or not fsops.matches(moved, artifact["inventory"]):
                raise Failure("trash_verification_failed", 6)
            fsops.apply_modes(moved, artifact["inventory"], private=True)
        fsops.fsync_dir(payload)
        for artifact in artifacts:
            fsops.fsync_dir(Path(artifact["source"]).parent)
        self._checkpoint("trash_verified", item["target_id"])
        with self.catalog.writer() as db:
            db.execute(
                "UPDATE sessions SET presence='trashed',current_trash_id=? WHERE uid=?",
                (entry["trash_id"], entry["session_uid"]),
            )
            db.execute(
                "UPDATE trash_entries SET state='trashed' WHERE trash_id=?", (entry["trash_id"],)
            )
        item["state"] = "trashed"
        item["error"] = None
        item["recovery_options"] = ["restore", "purge"]

    def _restore(self, op, target, item):
        entry, directory = self._entry(target["target_id"])
        self._validate_entry(entry, directory)
        item["trash_id"] = entry["trash_id"]
        self._save_item(op, item)
        root = self._root(entry["source_root"]["root_id"])
        if (
            public(root)["namespace_id"] != entry["source_root"]["namespace_id"]
            or str(root.path) != entry["source_root"]["path"]
            or root.executable_version != entry["source_root"].get("executable_version")
        ):
            raise Failure("restore_profile_changed", 5)
        self._closed_handles(entry["artifacts"])
        self._entry_state(entry["trash_id"], "restoring")
        for index, artifact in enumerate(entry["artifacts"]):
            source = directory / "payload" / str(index)
            destination = Path(artifact["source"])
            fsops.secure_path(destination.parent, root.path)
            if destination.exists():
                if not source.exists() and fsops.matches(
                    destination, artifact["inventory"], fingerprints=True
                ):
                    continue
                raise Failure("destination_conflict", 5)
            if not source.exists() or not fsops.matches(source, artifact["inventory"]):
                raise Failure("restore_payload_incomplete", 6)
            fsops.apply_modes(source, artifact["inventory"])
            fsops.move_noreplace(source, destination)
            self._checkpoint("restore_rename", item["target_id"])
            item["state"] = "restoring"
            item.setdefault("restored_artifacts", []).append(index)
            self._save_item(op, item)
        for artifact in entry["artifacts"]:
            if not fsops.matches(Path(artifact["source"]), artifact["inventory"]):
                raise Failure("restore_verification_failed", 6)
        with self.catalog.writer() as db:
            db.execute(
                "UPDATE sessions SET presence='present',current_trash_id=NULL WHERE uid=?",
                (entry["session_uid"],),
            )
            db.execute(
                "UPDATE trash_entries SET state='restored' WHERE trash_id=?", (entry["trash_id"],)
            )
        item.update(
            state="restored", trash_id=entry["trash_id"], error=None, recovery_options=["purge"]
        )

    def _purge(self, op, target, item):
        entry, directory = self._entry(target["target_id"])
        item["trash_id"] = entry["trash_id"]
        self._save_item(op, item)
        if entry["state"] == "purged":
            self._finish_purge(entry, directory)
            item.update(
                state="purged",
                trash_id=entry["trash_id"],
                error=None,
                recovery_options=[],
                cleanup_pending=False,
            )
            return
        self._validate_entry(entry, directory, subset=True)
        for category in ("payload", "backup"):
            self._closed_handles(entry["artifacts"], location=directory / category)
        self._entry_state(entry["trash_id"], "purging")
        for category in ("payload", "backup"):
            parent = directory / category
            if parent.exists():
                fsops.remove_owned_tree(parent)
                self._checkpoint("purge_tree", item["target_id"])
        with self.catalog.writer() as db:
            uid = entry["session_uid"]
            if db.execute(
                "SELECT 1 FROM sessions WHERE uid=? AND presence='trashed' AND current_trash_id=?",
                (uid, entry["trash_id"]),
            ).fetchone():
                from .models import Session, capabilities

                row = db.execute("SELECT payload FROM sessions WHERE uid=?", (uid,)).fetchone()
                session = Session.from_dict(json.loads(row[0]))
                session.title = session.preview = session.cwd = session.project_id = (
                    session.model
                ) = None
                session.extra = {}
                session.fingerprint = {}
                session.known_bytes = None
                session.capabilities = capabilities()
                session.history_state = session.search_state = session.usage_state = "unavailable"
                db.execute(
                    "UPDATE sessions SET presence='purged',payload=?,current_trash_id=NULL WHERE uid=?",
                    (json.dumps(public(session)), uid),
                )
                db.execute("DELETE FROM chunks WHERE uid=?", (uid,))
                db.execute("DELETE FROM jsonl_cursors WHERE uid=?", (uid,))
                db.execute("DELETE FROM event_memberships WHERE uid=?", (uid,))
                db.execute(
                    "DELETE FROM events WHERE event_uid NOT IN (SELECT event_uid FROM event_memberships)"
                )
            db.execute(
                "UPDATE trash_entries SET state='purged',payload=? WHERE trash_id=?",
                (
                    json.dumps(
                        public(
                            TrashEntry(
                                entry["trash_id"],
                                uid,
                                entry["operation_id"],
                                entry["source_root"],
                                entry["source_profile"],
                                entry["owner_uid"],
                                [],
                            )
                        )
                    ),
                    entry["trash_id"],
                ),
            )
        # Terminal receipt is committed before removing the final private manifest.
        self._checkpoint("purge_receipt", item["target_id"])
        self._finish_purge(entry, directory)
        item.update(
            state="purged",
            trash_id=entry["trash_id"],
            error=None,
            recovery_options=[],
            cleanup_pending=False,
        )

    def _finish_purge(self, entry, directory):
        # After the terminal receipt only the original manifest/empty directory
        # may remain. Never expand a retry's scope to newly introduced contents.
        parent = self.config.data_dir / "trash"
        fsops.secure_path(parent, self.config.data_dir)
        if not directory.exists() and not directory.is_symlink():
            fsops.fsync_dir(parent)
            return
        fsops.secure_path(directory, parent)
        if any(p.name != "manifest.json" for p in directory.iterdir()):
            raise Failure("unknown_trash_artifact", 5)
        manifest = directory / "manifest.json"
        if manifest.exists() or manifest.is_symlink():
            fsops.secure_path(manifest, directory)
            expected = self.catalog.connection.execute(
                "SELECT manifest_digest FROM trash_entries WHERE trash_id=?", (entry["trash_id"],)
            ).fetchone()[0]
            if digest(manifest.read_bytes()) != expected:
                raise Failure("trash_manifest_changed", 5)
        fsops.remove_owned_tree(directory)

    def commit(self, action, ids, token, *, assert_closed=False, _operation_id=None):
        ids = self._ids(action, ids)
        with self.lock():
            op, targets = self._load_plan(
                action, ids, token, assert_closed, operation_id=_operation_id
            )
            result = []
            for target in targets:
                row = self.catalog.connection.execute(
                    "SELECT payload FROM operation_items WHERE operation_id=? AND target_id=?",
                    (op, target["target_id"]),
                ).fetchone()
                item = json.loads(row[0])
                if item["state"] in (
                    "trashed",
                    "restored",
                    "purged",
                    "failed_no_change",
                ) and not item.get("cleanup_pending"):
                    result.append(item)
                    continue
                try:
                    if action == "trash":
                        self._trash(op, target, item)
                    elif action == "restore":
                        self._restore(op, target, item)
                    else:
                        self._purge(op, target, item)
                except (Failure, OSError) as error:
                    durable = (
                        self.catalog.connection.execute(
                            "SELECT state FROM trash_entries WHERE trash_id=?", (item["trash_id"],)
                        ).fetchone()
                        if item["trash_id"]
                        else None
                    )
                    if action == "purge" and durable and durable[0] == "purged":
                        item.update(
                            state="purged",
                            cleanup_pending=True,
                            error=error.code if isinstance(error, Failure) else "io_error",
                            recovery_options=["retry_same_confirmation", "inspect_trash"],
                        )
                    else:
                        changed = False
                        if item["trash_id"]:
                            parent = self.config.data_dir / "trash" / item["trash_id"] / "payload"
                            changed = parent.exists() and any(parent.iterdir())
                        if action in ("restore", "purge"):
                            changed = True
                        item["state"] = "recovery_required" if changed else "failed_no_change"
                        item["error"] = error.code if isinstance(error, Failure) else "io_error"
                        item["recovery_options"] = (
                            ["retry_same_confirmation", "inspect_trash"]
                            if changed
                            else ["new_preview"]
                        )
                        if item["trash_id"]:
                            self._entry_state(item["trash_id"], item["state"])
                self._save_item(op, item)
                result.append(item)
            terminal = all(
                item["state"] in ("trashed", "restored", "purged")
                and not item.get("cleanup_pending")
                for item in result
            )
            with self.catalog.writer() as db:
                db.execute(
                    "UPDATE operations SET state=? WHERE operation_id=?",
                    ("complete" if terminal else "partial", op),
                )
            return {"operation_id": op, "items": result}

    def trash_list(self):
        items = []
        for row in self.catalog.connection.execute(
            "SELECT trash_id,session_uid,state,operation_id FROM trash_entries ORDER BY rowid"
        ):
            state = row["state"]
            current = self.catalog.connection.execute(
                "SELECT i.operation_id,i.payload FROM operation_items i JOIN operations o USING(operation_id) WHERE i.target_id=? OR json_extract(i.payload,'$.trash_id')=? ORDER BY o.created_at DESC,o.rowid DESC LIMIT 1",
                (row["trash_id"], row["trash_id"]),
            ).fetchone()
            operation_id = current[0] if current else row["operation_id"]
            if state not in ("trashed", "restored", "purged", "failed_no_change"):
                state = "recovery_required"
            actions = (
                []
                if state == "purged"
                else ["purge"]
                if state == "restored"
                else ["restore", "purge"]
                if state == "trashed"
                else ["retry_same_confirmation", "inspect_trash"]
            )
            if state == "purged" and current:
                progress = json.loads(current[1])
                if progress.get("cleanup_pending") or progress["state"] != "purged":
                    actions = ["retry_same_confirmation", "inspect_trash"]
            items.append(
                {
                    "trash_id": row["trash_id"],
                    "session_id": row["session_uid"],
                    "state": state,
                    "operation_id": operation_id,
                    "available_actions": actions,
                }
            )
        return items

    def retry(self, operation_id, *, assert_closed=False):
        row = self.catalog.connection.execute(
            "SELECT action,ids FROM operation_plans WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if row is None:
            raise Failure("operation_not_found", 2)
        return self.commit(
            row["action"],
            json.loads(row["ids"]),
            None,
            assert_closed=assert_closed,
            _operation_id=operation_id,
        )
