from pathlib import Path

from ..models import Capability, Failure, Session, annotate_dates, timestamp
from .base import (
    RECORD_ERRORS,
    ScanResult,
    available_root,
    discover_paths,
    fingerprint,
    json_lines,
    resume_capability,
)
from .sqlite_reader import NativeSQLite


class Adapter:
    profile = "codex-paginated-0.166"

    def __init__(self, root):
        self.root = root

    def discover(self):
        root = self.root
        path = root.path / "state_5.sqlite"
        result = ScanResult(profile=self.profile)
        if not available_root(root.path, result):
            return result
        if path.exists():
            stamps = {
                "state": fingerprint(path),
                "state_wal": fingerprint(path.with_name(path.name + "-wal")),
                "projection": fingerprint(root.path / "thread_history_1.sqlite"),
                "projection_wal": fingerprint(root.path / "thread_history_1.sqlite-wal"),
            }
            # Optional columns vary; only whitelisted names are ever selected.

            with NativeSQLite(path, {"threads": {"id"}}, closed_snapshot=True) as reader:
                actual = {r[1] for r in reader.connection.execute('PRAGMA table_info("threads")')}
                allowed = {
                    "id",
                    "rollout_path",
                    "cwd",
                    "title",
                    "preview",
                    "name",
                    "model",
                    "created_at",
                    "created_at_ms",
                    "updated_at",
                    "updated_at_ms",
                    "recency_at",
                    "recency_at_ms",
                    "history_mode",
                    "archived",
                }
                columns = allowed & actual
                reader.tables["threads"] = columns
                rows = reader.read("threads", sorted(columns))
            for row in rows:
                try:
                    if "archived" in row and (
                        type(row["archived"]) is not int or row["archived"] not in (0, 1)
                    ):
                        raise Failure("invalid_native_record", 3)
                    locator = Path(
                        row.get("rollout_path") or root.path / "sessions" / (row["id"] + ".jsonl")
                    )
                    session = Session.build(
                        root,
                        row["id"],
                        locator,
                        cwd=row.get("cwd"),
                        title=row.get("title") or row.get("name"),
                        preview=row.get("preview"),
                        model=row.get("model"),
                        created_at=timestamp(
                            row.get("created_at_ms") or row.get("created_at"),
                            milliseconds=bool(row.get("created_at_ms")),
                        ),
                        last_activity_at=timestamp(
                            row.get("recency_at_ms")
                            or row.get("updated_at_ms")
                            or row.get("recency_at")
                            or row.get("updated_at")
                        ),
                        profile=self.profile,
                        fingerprint={
                            **stamps,
                            "rollout": fingerprint(locator),
                        },
                        extra={
                            "history_mode": row.get("history_mode"),
                            "archived": bool(row.get("archived", False)),
                            "archive_state_known": "archived" in row,
                        },
                    )
                    annotate_dates(
                        session,
                        [row.get("created_at_ms") or row.get("created_at")],
                        [
                            row.get("recency_at_ms")
                            or row.get("updated_at_ms")
                            or row.get("recency_at")
                            or row.get("updated_at")
                        ],
                    )
                    self._capabilities(session, locator.is_file())
                    result.sessions.append(session)
                except RECORD_ERRORS:
                    result.complete, result.reason = False, "invalid_native_record"
        else:
            for locator in discover_paths(root.path / "sessions", "**/*.jsonl", result):
                try:
                    _, row = next(json_lines(locator, cache=getattr(self, "jsonl_cache", None)))
                    meta = row.get("payload", {})
                    if row.get("type") != "session_meta" or not meta.get("id"):
                        raise Failure("unsupported_native_schema", 3)
                    session = Session.build(
                        root,
                        meta["id"],
                        locator,
                        cwd=meta.get("cwd"),
                        created_at=timestamp(meta.get("timestamp")),
                        profile="codex-jsonl",
                        fingerprint={"rollout": fingerprint(locator)},
                    )
                    annotate_dates(session, [meta.get("timestamp")], [])
                    self._capabilities(session, True)
                    result.sessions.append(session)
                except (*RECORD_ERRORS, StopIteration):
                    result.complete, result.reason = False, "invalid_native_record"
        return result

    def _capabilities(self, session, has_rollout):
        session.capabilities["metadata"] = Capability("supported")
        session.capabilities["cleanup"] = Capability("unavailable", "native_cascade_unbounded")
        if getattr(self, "metadata_only", False):
            return
        from .native_version import resolve_cleanup_version

        paginated = (
            session.extra.get("history_mode") == "paginated"
            and resolve_cleanup_version(self.root) == "0.166.0"
        )
        if (
            paginated
            and session.extra.get("archive_state_known")
            and resume_capability(self.root).state == "supported"
        ):
            name = "unarchive" if session.extra.get("archived") else "archive"
            session.capabilities[name] = Capability("supported")
        persisted = has_rollout or (paginated and self._has_paginated_history(session.native_id))
        if session.extra.get("archived"):
            session.capabilities["resume"] = Capability("unavailable", "native_archived")
        elif persisted:
            session.capabilities["resume"] = resume_capability(self.root)
        else:
            session.capabilities["resume"] = Capability(
                "unavailable",
                "history_not_recorded"
                if paginated and not persisted
                else "resume_binding_unverified",
            )

    def _has_paginated_history(self, native_id):
        if not hasattr(self, "_persisted_threads"):
            import sqlite3

            self._persisted_threads = set()
            tables = {"thread_items": {"thread_id"}, "thread_realtime_items": {"thread_id"}}
            try:
                with NativeSQLite(
                    self.root.path / "thread_history_1.sqlite", tables, closed_snapshot=True
                ) as reader:
                    for table in tables:
                        self._persisted_threads.update(
                            row["thread_id"] for row in reader.read(table, ["thread_id"])
                        )
            except (Failure, OSError, sqlite3.Error):
                # An index row alone does not establish recoverable conversation context.
                self._persisted_threads.clear()
        return native_id in self._persisted_threads

    def read_history(self, session):
        import json
        from collections import defaultdict

        from ..models import HistoryResult

        events = {}
        state = "complete"
        native_events = False
        db = self.root.path / "thread_history_1.sqlite"
        try:
            if not hasattr(self, "_projection"):
                self._projection = defaultdict(list)
                if db.is_file():
                    tables = {
                        "thread_items": {
                            "thread_id",
                            "turn_id",
                            "item_id",
                            "rollout_ordinal",
                            "item_json",
                            "created_at_ms",
                        },
                        "thread_realtime_items": {
                            "thread_id",
                            "item_id",
                            "rollout_ordinal",
                            "item_json",
                            "created_at_ms",
                        },
                    }
                    with NativeSQLite(db, tables, closed_snapshot=True) as reader:
                        for table in tables:
                            for row in reader.read(table, sorted(tables[table])):
                                self._projection[row["thread_id"]].append(row)
            for row in self._projection.get(session.native_id, []):
                item = row["item_json"]
                if isinstance(item, str):
                    item = json.loads(item)
                    # Share decoded text with normalized events, releasing large raw JSON.
                    row["item_json"] = item
                if not isinstance(item, dict):
                    state = "partial"
                    continue
                event = self._item(
                    session, item, row["item_id"], row["rollout_ordinal"], row.get("created_at_ms")
                )
                if event:
                    event.turn_id = row.get("turn_id")
                    if event.completeness != "complete":
                        state = "partial"
                if event is None:
                    state = "partial"
                else:
                    previous = events.get(event.native_id)
                    if previous and (previous.role != event.role or previous.text != event.text):
                        state = "partial"
                    else:
                        events[event.native_id] = event
            path = Path(session.locator)
            if path.is_file():
                for ordinal, row in json_lines(path, cache=getattr(self, "jsonl_cache", None)):
                    payload = row.get("payload", {})
                    if row.get("type") == "response_item":
                        native = payload.get("id")
                        if not native:
                            state = "partial"
                            continue
                        checked = self._item(
                            session, payload, native, ordinal, timestamp(row.get("timestamp"))
                        )
                        native_events = native_events or (
                            checked is not None and checked.completeness == "complete"
                        )
                        if native in events:
                            continue
                        event = checked
                        if event:
                            events[native] = event
                            if event.completeness != "complete":
                                state = "partial"
                        else:
                            state = "partial"
                    elif row.get("type") in ("compacted",):
                        state = "partial"
            elif not events:
                return HistoryResult([], "unavailable", "history_not_recorded")
        except (Failure, OSError, ValueError):
            state = "partial"
        observed = {
            "state": self.root.path / "state_5.sqlite",
            "state_wal": self.root.path / "state_5.sqlite-wal",
            "projection": db,
            "projection_wal": db.with_name(db.name + "-wal"),
            "rollout": Path(session.locator),
        }
        if any(
            key in session.fingerprint and session.fingerprint[key] != fingerprint(path)
            for key, path in observed.items()
        ):
            state = "partial"
        session._native_history_verified = native_events and state == "complete"
        return HistoryResult(sorted(events.values(), key=lambda e: (e.ordinal, e.event_uid)), state)

    def _item(self, session, item, native, ordinal, created):
        from ..models import HistoryEvent, identity

        kind = item.get("type")
        role = None
        text = None
        completeness = "complete"
        if kind in ("userMessage", "message"):
            role = item.get("role", "user") if kind == "message" else "user"
            if role not in ("user", "assistant"):
                return None
            content = item.get("content", [])
            text = (
                content
                if isinstance(content, str)
                else "\n".join(
                    b.get("text", "")
                    for b in content
                    if b.get("type") in ("text", "inputText", "input_text", "output_text")
                )
            )
        elif kind == "agentMessage":
            role = "assistant"
            text = item.get("text", "")
        elif kind in ("commandExecution", "mcpToolCall", "fileChange", "function_call"):
            role = "tool_call"
            text = item.get("command") or item.get("name") or "File changes"
        elif kind in ("function_call_output",):
            role = "tool_result"
            text = item.get("output")
            if isinstance(text, list):
                pieces = []
                for block in text:
                    if (
                        isinstance(block, dict)
                        and block.get("type") in ("text", "input_text", "output_text")
                        and isinstance(block.get("text"), str)
                    ):
                        pieces.append(block["text"])
                    else:
                        pieces.append("[Non-text content omitted]")
                        completeness = "partial"
                text = "\n".join(pieces)
        elif kind in ("reasoning", "contextCompaction"):
            return None
        else:
            return None
        if text is not None and not isinstance(text, str):
            return None
        return HistoryEvent(
            identity(session.namespace_id, session.native_id, native),
            role,
            ordinal,
            text=text,
            timestamp=created,
            native_id=native,
            locator=session.locator,
            completeness=completeness,
        )

    def prepare_cleanup_bundle(self, session):
        from .base import prepare_cleanup_bundle

        return prepare_cleanup_bundle(self.root, session)

    def read_usage(self, session):
        from ..models import (
            TOKEN_CATEGORIES,
            UsageFact,
            UsageMembership,
            UsageResult,
            UsageSnapshot,
            identity,
        )
        from .base import usage_counts

        result = UsageResult()
        facts = {}
        snapshot = None
        snapshot_incomplete = False
        mapping = {
            "input_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "cache_read_tokens": "cached_input_tokens",
            "cache_write_tokens": "cache_write_input_tokens",
            "reasoning_tokens": "reasoning_output_tokens",
            "total_tokens": "total_tokens",
        }
        path = Path(session.locator)
        if not path.is_file():
            return UsageResult(state="unavailable", reason="not_recorded")
        try:
            for ordinal, row in json_lines(path, cache=getattr(self, "jsonl_cache", None)):
                payload = row.get("payload", {})
                if not isinstance(payload, dict):
                    result.state = "partial"
                    continue
                if row.get("type") == "token_usage_record" and isinstance(
                    payload.get("usage"), dict
                ):
                    request = payload.get("response_id")
                    owner = payload.get("thread_id")
                    if not request or not owner:
                        result.state = "partial"
                        continue
                    values = usage_counts(payload["usage"], mapping)
                    uid = identity(session.namespace_id, "usage", request)
                    fact = UsageFact(
                        uid,
                        "codex",
                        session.namespace_id,
                        request,
                        owner_native_session_id=owner,
                        **values,
                    )
                    if uid in facts and any(
                        getattr(facts[uid], key) != getattr(fact, key) for key in TOKEN_CATEGORIES
                    ):
                        fact = UsageFact(
                            uid,
                            "codex",
                            session.namespace_id,
                            request,
                            owner_native_session_id=owner,
                            completeness="partial",
                        )
                        result.state = "partial"
                    facts[uid] = fact
                    if owner != session.native_id:
                        result.state = "partial"
                elif row.get("type") == "event_msg" and payload.get("type") == "token_count":
                    info = payload.get("info")
                    if info is None:
                        continue
                    if not isinstance(info, dict):
                        result.state = "partial"
                        continue
                    raw = info.get("total_token_usage")
                    if isinstance(raw, dict):
                        values = usage_counts(raw, mapping)
                        if snapshot and any(
                            snapshot.values[key] is not None
                            and values[key] is not None
                            and values[key] < snapshot.values[key]
                            for key in TOKEN_CATEGORIES
                        ):
                            snapshot_incomplete = True
                        snapshot = UsageSnapshot(
                            session.session_uid,
                            "codex-thread:" + session.native_id,
                            "current",
                            values,
                            completeness="partial" if snapshot_incomplete else "complete",
                            native_revision={"ordinal": ordinal},
                        )
                elif row.get("type") == "compacted":
                    snapshot_incomplete = True
        except (OSError, Failure, ValueError):
            result.state = "partial"
            result.reason = "usage_incomplete"
        result.facts = list(facts.values())
        result.memberships = [
            UsageMembership(identity(session.namespace_id, f.owner_native_session_id), f.fact_uid)
            for f in result.facts
        ]
        if snapshot:
            if snapshot_incomplete:
                snapshot.completeness = "partial"
            result.snapshots = [snapshot]
        if snapshot_incomplete or (snapshot and facts):
            result.state = "partial"
            result.reason = "usage_scope_unverified"
        if not facts and not snapshot and result.state == "complete":
            result.state = "unavailable"
            result.reason = "not_recorded"
        return result
