"""Native Codex archive with exact preview, verified cascades and private recovery.

Only native RPC changes source data. The closed-set assertion is a precondition,
not a lock on other Codex processes. Native success is verified per confirmed ID.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import selectors
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

from . import fsops
from .cleanup import CleanupService
from .models import Failure, identity, now_ms, public
from .sources.base import fingerprint, resume_context_verified
from .sources.native_version import resolve_cleanup_version
from .sources.sqlite_reader import NativeSQLite


def checksum(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class NativeClient:
    """Bounded stdio RPC; no conversation methods and no transcript diagnostics."""

    def __init__(self, root, *, env=None):
        self.root, self.sequence, self.pending = root, 0, b""
        self.env = env

    def __enter__(self):
        self.child = subprocess.Popen(
            [
                str(self.root.executable_path),
                "app-server",
                "--stdio",
                "-c",
                "analytics.enabled=false",
            ],
            cwd="/",
            env={
                **(os.environ if self.env is None else self.env),
                "CODEX_HOME": str(self.root.path),
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.child.stdout, selectors.EVENT_READ)
        try:
            self.call(
                "initialize",
                {"clientInfo": {"name": "sessions-manager-archive", "version": "0.1.0"}},
            )
            self.child.stdin.write(b'{"method":"initialized"}\n')
            self.child.stdin.flush()
        except BaseException:
            self.__exit__()
            raise
        return self

    def call(self, method, params):
        if method not in ("initialize", "thread/archive", "thread/unarchive"):
            raise Failure("native_archive_method_unavailable", 4)
        self.sequence += 1
        try:
            self.child.stdin.write(
                (
                    json.dumps({"id": self.sequence, "method": method, "params": params}) + "\n"
                ).encode()
            )
            self.child.stdin.flush()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                while b"\n" in self.pending:
                    line, self.pending = self.pending.split(b"\n", 1)
                    message = json.loads(line)
                    if message.get("id") == self.sequence:
                        if "result" not in message:
                            raise Failure("native_archive_failed", 8)
                        return message["result"]
                if len(self.pending) > 4 * 1024 * 1024:
                    raise Failure("native_archive_protocol_error", 8)
                if self.selector.select(0.1):
                    chunk = os.read(self.child.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    self.pending += chunk
        except (OSError, ValueError, AttributeError):
            raise Failure("native_archive_io_error", 8) from None
        raise Failure("native_archive_timeout", 8)

    def __exit__(self, *args):
        self.child.stdin.close()
        try:
            self.child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.child.terminate()
            try:
                self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=2)
        self.child.stdout.close()
        self.selector.close()


def descendants(edges, start):
    ordered, visiting, seen = [], set(), set()
    stack = [(start, False)]
    while stack:
        tid, leaving = stack.pop()
        if leaving:
            visiting.remove(tid)
            continue
        if tid in visiting:
            raise Failure("archive_graph_unavailable", 4)
        if tid in seen:
            continue
        if len(seen) >= 10000:
            raise Failure("archive_graph_limit", 4)
        visiting.add(tid)
        seen.add(tid)
        ordered.append(tid)
        stack.append((tid, True))
        stack.extend((child, False) for child in sorted(edges.get(tid, []), reverse=True))
    return ordered


def native_snapshot(root, tid):
    """Read only supported native tables; persist hashes, never transcript bodies."""
    state = root.path / "state_5.sqlite"
    history = root.path / "thread_history_1.sqlite"
    paths = [state, history]
    for base in list(paths):
        paths += [
            base.with_name(base.name + s)
            for s in ("-wal", "-shm")
            if base.with_name(base.name + s).exists()
        ]
    for path in paths:
        fsops.secure_path(path, root.path)
    with NativeSQLite(
        state,
        {
            "threads": {"id", "cwd", "history_mode", "archived", "rollout_path"},
            "thread_spawn_edges": {"parent_thread_id", "child_thread_id"},
        },
        closed_snapshot=True,
    ) as reader:
        reader.connection.execute("BEGIN")
        rows = {
            r["id"]: r
            for r in reader.read(
                "threads", ["id", "cwd", "history_mode", "archived", "rollout_path"]
            )
        }
        edges = {}
        for edge in reader.read("thread_spawn_edges", ["parent_thread_id", "child_thread_id"]):
            edges.setdefault(edge["parent_thread_id"], []).append(edge["child_thread_id"])
        order = descendants(edges, tid)
        if any(member not in rows for member in order):
            raise Failure("archive_graph_unavailable", 4)
        graph = {member: sorted(edges.get(member, [])) for member in order}
        members = {}
        tables = {
            "thread_items": {"thread_id", "item_id", "item_json", "turn_id", "rollout_ordinal"},
            "thread_realtime_items": {"thread_id", "item_id", "item_json", "rollout_ordinal"},
        }
        with NativeSQLite(history, tables, closed_snapshot=True) as contents:
            contents.connection.execute("BEGIN")
            for member in order:
                row = rows[member]
                if (
                    row["history_mode"] != "paginated"
                    or type(row["archived"]) is not int
                    or row["archived"] not in (0, 1)
                ):
                    raise Failure("archive_profile_unverified", 4)
                digest = hashlib.sha256(
                    json.dumps([row["id"], row["cwd"], row["history_mode"]]).encode()
                )
                for table, columns in tables.items():
                    events = contents.read(table, sorted(columns), key="thread_id", value=member)
                    digest.update(
                        json.dumps(
                            sorted(events, key=lambda e: (e["rollout_ordinal"], e["item_id"])),
                            sort_keys=True,
                        ).encode()
                    )
                rollout = Path(row["rollout_path"]) if row["rollout_path"] else None
                if rollout:
                    if ".." in rollout.parts or not rollout.is_relative_to(root.path):
                        raise Failure("path_outside_source_root", 5)
                    if rollout.is_symlink():
                        raise Failure("unsafe_artifact_owner_or_link", 5)
                if rollout and rollout.exists():
                    inventory = fsops.inventory(rollout, root.path)
                    digest.update(inventory["."]["sha256"].encode())
                members[member] = {
                    "archived": bool(row["archived"]),
                    "revision": digest.hexdigest(),
                }
    return {"members": members, "graph": graph, "order": order, "paths": list(map(str, paths))}


TERMINAL = ("complete", "failed_no_change")


def validate_plan(value):
    """Treat persisted plans as input; reject malformed scope before any RPC."""
    try:
        plan = json.loads(value) if isinstance(value, str) else value
        snapshot, binding = plan["snapshot"], plan["binding"]
        members, graph, order = snapshot["members"], snapshot["graph"], snapshot["order"]
        if (
            plan["action"] not in ("archive", "unarchive")
            or not isinstance(members, dict)
            or not 1 <= len(members) <= 10000
            or not isinstance(graph, dict)
            or set(graph) != set(members)
            or not isinstance(order, list)
        ):
            raise ValueError()
        if any(
            not isinstance(tid, str) or not tid or len(tid) > 256 or "\0" in tid for tid in members
        ):
            raise ValueError()
        if any(
            not isinstance(children, list)
            or len(set(children)) != len(children)
            or not set(children) <= set(members)
            for children in graph.values()
        ):
            raise ValueError()
        if order != descendants(graph, plan["native_id"]) or set(order) != set(members):
            raise ValueError()
        for key in ("before", "desired"):
            if set(plan[key]) != set(members) or any(
                type(v) is not bool for v in plan[key].values()
            ):
                raise ValueError()
        for tid, member in members.items():
            revision = member["revision"]
            if (
                type(member["archived"]) is not bool
                or member["archived"] != plan["before"][tid]
                or not isinstance(revision, str)
                or len(revision) != 64
                or any(c not in "0123456789abcdef" for c in revision)
            ):
                raise ValueError()
        for key in ("root_id", "namespace", "path", "executable"):
            if not isinstance(binding[key], str) or not binding[key] or "\0" in binding[key]:
                raise ValueError()
        if not all(Path(binding[k]).is_absolute() for k in ("path", "executable")):
            raise ValueError()
        stamp = binding["fingerprint"]
        if any(
            type(stamp[k]) is not int or stamp[k] < 0 for k in ("dev", "inode", "size", "mtime_ns")
        ):
            raise ValueError()
        if plan["selector"] != "s-" + identity(binding["namespace"], plan["native_id"]):
            raise ValueError()
        if plan["before"][plan["native_id"]] != (plan["action"] == "unarchive"):
            raise ValueError()
        if (plan["action"] == "archive" and not all(plan["desired"].values())) or (
            plan["action"] == "unarchive" and plan["desired"][plan["native_id"]]
        ):
            raise ValueError()
        return plan
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, Failure):
        raise Failure("archive_journal_invalid", 6) from None


def load_operation(value):
    try:
        op = json.loads(value)
        plan = validate_plan(op["plan"])
        if (
            op["action"] != plan["action"]
            or op["state"] not in (*TERMINAL, "running", "recovery_required")
            or not isinstance(op["operation_id"], str)
            or not op["operation_id"]
            or set(op["flags"]) != set(plan["before"])
            or any(type(v) is not bool for v in op["flags"].values())
            or type(op.get("native_started", False)) is not bool
        ):
            raise ValueError()
        intent = op["intent"]
        if intent is not None and (
            intent["id"] not in plan["before"] or type(intent["archived"]) is not bool
        ):
            raise ValueError()
        return op
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise Failure("archive_journal_invalid", 6) from None


class ArchiveService:
    def __init__(self, config, catalog, *, client_factory=NativeClient, fault=None):
        self.config, self.catalog = config, catalog
        self.client_factory, self.fault = client_factory, fault
        self.lock = CleanupService(config, catalog).lock
        with catalog.writer() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS native_archive_plans(token TEXT PRIMARY KEY,action TEXT,selector TEXT,payload TEXT,expires INTEGER,operation_id TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS native_archive_operations(id TEXT PRIMARY KEY,payload TEXT)"
            )

    def _root(self, root_id):
        root = next((r for r in self.config.roots if r.enabled and r.root_id == root_id), None)
        if (
            root is None
            or root.provider != "codex"
            or not resume_context_verified(root)
            or resolve_cleanup_version(root) != "0.166.0"
        ):
            raise Failure("archive_profile_unverified", 4)
        from dataclasses import replace

        if resolve_cleanup_version(replace(root, executable_version=None)) != "0.166.0":
            raise Failure("archive_profile_unverified", 4)
        root.path = fsops.trusted_directory(root.path)
        info = root.executable_path.resolve().stat()
        if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
            raise Failure("unsafe_executable", 5)
        return root

    def _binding(self, root):
        return {
            "root_id": root.root_id,
            "path": str(root.path),
            "namespace": root.namespace_id,
            "executable": str(root.executable_path),
            "fingerprint": fingerprint(root.executable_path.resolve()),
        }

    def _safe(self, root, snapshot, *, handles=True):
        for tid in snapshot["order"]:
            uid = identity(root.namespace_id, tid)
            row = self.catalog.connection.execute(
                "SELECT payload FROM sessions WHERE uid=?", (uid,)
            ).fetchone()
            if row:
                session = self.catalog.get(uid)
                if session.activity == "active":
                    raise Failure("session_active", 5)
                if (
                    session.extra.get("identity_conflict")
                    or len(session.extra.get("identity_signatures", {})) > 1
                ):
                    raise Failure("multiple_locations_unverified", 4)
                if session.presence != "present":
                    raise Failure("source_not_present", 5)
            locations = self.catalog.connection.execute(
                "SELECT COUNT(*) FROM locations WHERE uid=?", (uid,)
            ).fetchone()[0]
            if locations > 1:
                raise Failure("multiple_locations_unverified", 4)
        if handles and fsops.open_handles([Path(p) for p in snapshot["paths"]]):
            raise Failure("observed_open_handle", 5)

    def _capture(self, root, tid, *, handles=True):
        value = native_snapshot(root, tid)
        self._safe(root, value, handles=handles)
        return value

    def _check(self, root, plan, *, handles=True):
        current = self._capture(root, plan["native_id"], handles=handles)
        if (
            self._binding(root) != plan["binding"]
            or current["graph"] != plan["snapshot"]["graph"]
            or {k: v["revision"] for k, v in current["members"].items()}
            != {k: v["revision"] for k, v in plan["snapshot"]["members"].items()}
        ):
            raise Failure("archive_source_changed", 5)
        return current

    def preview(self, action, selector):
        if action not in ("archive", "unarchive"):
            raise Failure("invalid_operation", 2)
        session = self.catalog.get(selector)
        root = self._root(session.root_id)
        for operation in self._all_operations():
            if (
                operation["plan"]["binding"]["root_id"] == root.root_id
                and operation["state"] not in TERMINAL
            ):
                raise Failure(
                    "archive_operation_pending", 5, data={"operation_id": operation["operation_id"]}
                )
        snapshot = self._capture(root, session.native_id)
        before = {k: v["archived"] for k, v in snapshot["members"].items()}
        if before[session.native_id] != (action == "unarchive"):
            raise Failure("native_archive_state_changed", 5)
        desired = (
            dict.fromkeys(before, True)
            if action == "archive"
            else {**before, session.native_id: False}
        )
        if action == "unarchive":
            prior = next(
                (
                    op
                    for op in reversed(self._all_operations())
                    if op["state"] == "complete"
                    and op["action"] == "archive"
                    and op["plan"]["selector"] == session.display_id
                ),
                None,
            )
            if prior:
                if prior["plan"]["snapshot"]["graph"] != snapshot["graph"]:
                    raise Failure("archive_source_changed", 5)
                desired = prior["plan"]["before"]
        plan = {
            "action": action,
            "selector": session.display_id,
            "native_id": session.native_id,
            "binding": self._binding(root),
            "snapshot": snapshot,
            "before": before,
            "desired": desired,
        }
        token, expires = secrets.token_hex(32), now_ms() + 300000
        with self.catalog.writer() as db:
            db.execute(
                "INSERT INTO native_archive_plans VALUES (?,?,?,?,?,NULL)",
                (checksum(token), action, session.display_id, json.dumps(plan), expires),
            )
        return {
            "action": action,
            "confirmation_token": token,
            "expires_at": expires,
            "members": self._members(plan, before),
            "requires_assert_closed": True,
            "effect": "Native Codex archive; history stays on disk. Both operations may temporarily cascade over every listed session; original archived flags are reconciled.",
        }

    def _members(self, plan, flags):
        return [
            {
                "session_id": "s-" + identity(plan["binding"]["namespace"], tid),
                "native_id": tid,
                "before_archived": plan["before"][tid],
                "desired_archived": plan["desired"][tid],
                "archived": flags[tid],
            }
            for tid in plan["snapshot"]["order"]
        ]

    def _save(self, operation):
        with self.catalog.writer() as db:
            db.execute(
                "INSERT OR REPLACE INTO native_archive_operations VALUES (?,?)",
                (operation["operation_id"], json.dumps(operation)),
            )

    def _all_operations(self):
        return [
            load_operation(r[0])
            for r in self.catalog.connection.execute(
                "SELECT payload FROM native_archive_operations ORDER BY rowid"
            )
        ]

    def _result(self, op):
        return {
            "operation_id": op["operation_id"],
            "action": op["action"],
            "state": op["state"],
            "members": self._members(op["plan"], op["flags"]),
            "error": op.get("error"),
            "recovery_options": (
                []
                if op["state"] == "complete"
                else ["new_preview"]
                if op["state"] == "failed_no_change"
                else ["archive-retry"]
            ),
        }

    def operations(self):
        return [self._result(op) for op in self._all_operations()]

    def commit(self, action, selector, token, *, assert_closed=False):
        if not assert_closed:
            raise Failure("closed_assertion_required", 7)
        selector = self.catalog.get(selector).display_id
        with self.lock():
            row = self.catalog.connection.execute(
                "SELECT * FROM native_archive_plans WHERE token=?", (checksum(token),)
            ).fetchone()
            if row is None or row["action"] != action or row["selector"] != selector:
                raise Failure("confirmation_mismatch", 7)
            if row["operation_id"]:
                return self._retry(row["operation_id"])
            if row["expires"] < now_ms():
                raise Failure("confirmation_expired", 7)
            plan = validate_plan(row["payload"])
            if plan["action"] != action or plan["selector"] != selector:
                raise Failure("archive_journal_invalid", 6)
            root = self._root(plan["binding"]["root_id"])
            current = self._check(root, plan)
            if {k: v["archived"] for k, v in current["members"].items()} != plan["before"]:
                raise Failure("archive_source_changed", 5)
            if any(
                op["state"] not in TERMINAL and op["plan"]["binding"]["root_id"] == root.root_id
                for op in self._all_operations()
            ):
                raise Failure("archive_operation_pending", 5)
            op = {
                "operation_id": str(uuid.uuid4()),
                "action": action,
                "plan": plan,
                "flags": plan["before"].copy(),
                "intent": None,
                "native_started": False,
                "state": "running",
                "error": None,
            }
            with self.catalog.writer() as db:
                db.execute(
                    "INSERT INTO native_archive_operations VALUES (?,?)",
                    (op["operation_id"], json.dumps(op)),
                )
                db.execute(
                    "UPDATE native_archive_plans SET operation_id=? WHERE token=?",
                    (op["operation_id"], checksum(token)),
                )
            return self._run(root, op)

    def retry(self, operation_id, *, assert_closed=False):
        if not assert_closed:
            raise Failure("closed_assertion_required", 7)
        with self.lock():
            return self._retry(operation_id)

    def _retry(self, operation_id):
        row = self.catalog.connection.execute(
            "SELECT payload FROM native_archive_operations WHERE id=?", (operation_id,)
        ).fetchone()
        if row is None:
            raise Failure("operation_not_found", 2)
        op = load_operation(row[0])
        if op["state"] in TERMINAL:
            return self._result(op)
        try:
            root = self._root(op["plan"]["binding"]["root_id"])
            return self._run(root, op)
        except Failure as error:
            op.update(
                state="recovery_required" if op.get("native_started") else "failed_no_change",
                error=error.code,
            )
            self._save(op)
            return self._result(op)

    def _observe(self, root, op, *, handles):
        snapshot = self._check(root, op["plan"], handles=handles)
        actual = {k: v["archived"] for k, v in snapshot["members"].items()}
        intent = op["intent"]
        affected = descendants(op["plan"]["snapshot"]["graph"], intent["id"]) if intent else []
        if any(
            value != op["flags"][tid] and not (tid in affected and value == intent["archived"])
            for tid, value in actual.items()
        ):
            raise Failure("archive_source_changed", 5)
        op["flags"], op["intent"] = actual, None
        self._save(op)
        with self.catalog.writer() as db:
            for tid, flag in actual.items():
                uid = identity(root.namespace_id, tid)
                if not db.execute("SELECT 1 FROM sessions WHERE uid=?", (uid,)).fetchone():
                    continue
                session = self.catalog.get(uid)
                session.extra.update(archived=flag, native_archive_observed_at=now_ms())
                session.history_state = session.search_state = "stale"
                session.usage_state = "partial"
                for key in ("identity_digest", "identity_digest_version", "usage_version"):
                    session.extra.pop(key, None)
                from .models import Capability

                session.capabilities["resume"] = Capability(
                    "unavailable", "native_archived" if flag else "scan_pending"
                )
                db.execute(
                    "UPDATE sessions SET payload=? WHERE uid=?", (json.dumps(public(session)), uid)
                )
                evidence = {"session": public(session), "cycle": None, "stage": "metadata"}
                db.execute(
                    "UPDATE locations SET payload=? WHERE uid=? AND root_id=?",
                    (json.dumps(evidence), uid, root.root_id),
                )
        return actual

    def _run(self, root, op):
        try:
            actual = self._observe(root, op, handles=True)
            if actual != op["plan"]["desired"]:
                with self.client_factory(root) as client:
                    for tid in op["plan"]["snapshot"]["order"]:
                        if actual[tid] == op["plan"]["desired"][tid]:
                            continue
                        self._check(root, op["plan"], handles=False)
                        op["intent"] = {"id": tid, "archived": op["plan"]["desired"][tid]}
                        op["native_started"] = True
                        self._save(op)
                        if self.fault:
                            self.fault("before_native")
                        client.call(
                            "thread/archive" if op["intent"]["archived"] else "thread/unarchive",
                            {"threadId": tid},
                        )
                        if self.fault:
                            self.fault("after_native")
                        actual = self._observe(root, op, handles=False)
            if actual != op["plan"]["desired"]:
                raise Failure("native_archive_partial", 8)
            self._reconcile_catalog(root, op)
            op.update(state="complete", error=None)
        except (Failure, OSError, sqlite3.Error) as error:
            op.update(
                state="recovery_required" if op.get("native_started") else "failed_no_change",
                error=error.code if isinstance(error, Failure) else "native_archive_io_error",
            )
        self._save(op)
        return self._result(op)

    def _reconcile_catalog(self, root, op):
        from .discovery import adapter

        # Read fresh native metadata once after the writer closes. Retain the
        # existing indexed history/usage/hidden state; no shared-store rollback.
        result = adapter(root).discover()
        fresh = {s.native_id: s for s in result.sessions}
        current = self._check(root, op["plan"])
        if {k: v["archived"] for k, v in current["members"].items()} != op["flags"]:
            raise Failure("archive_source_changed", 5)
        with self.catalog.writer() as db:
            for tid, flag in op["flags"].items():
                if tid not in fresh or fresh[tid].extra.get("archived") != flag:
                    raise Failure("archive_source_changed", 5)
                uid = identity(root.namespace_id, tid)
                if not db.execute("SELECT 1 FROM sessions WHERE uid=?", (uid,)).fetchone():
                    continue
                session = self.catalog.get(uid)
                session.extra["archived"] = flag
                session.fingerprint, session.locator = fresh[tid].fingerprint, fresh[tid].locator
                for name in ("resume", "archive", "unarchive"):
                    session.capabilities[name] = fresh[tid].capabilities[name]
                db.execute(
                    "UPDATE sessions SET payload=? WHERE uid=?", (json.dumps(public(session)), uid)
                )
                evidence = {"session": public(session), "cycle": None, "stage": "metadata"}
                db.execute(
                    "UPDATE locations SET locator=?,payload=? WHERE uid=? AND root_id=?",
                    (session.locator, json.dumps(evidence), uid, root.root_id),
                )

    def list(self):
        return {
            "cached": True,
            "items": [
                public(s)
                for s in self.catalog.sessions(include_missing=True)
                if s.provider == "codex" and s.presence == "present" and s.extra.get("archived")
            ],
            "operations": self.operations(),
        }
