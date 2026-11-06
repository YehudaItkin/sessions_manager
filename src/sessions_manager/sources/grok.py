from ..models import Capability, Failure, Session, annotate_dates, timestamp
from .base import (
    ScanResult,
    available_root,
    directory_inventory,
    discover_paths,
    fingerprint,
    json_file,
    read_many,
    resume_capability,
)


class Adapter:
    profile = "grok-build-1.0.70"

    def __init__(self, root):
        self.root = root

    def discover(self):
        result = ScanResult(profile=self.profile)
        if not available_root(self.root.path, result):
            return result
        home = (
            self.root.path / "sessions"
            if (self.root.path / "sessions").is_dir()
            else self.root.path
        )
        for session in read_many(
            self._discover_one,
            discover_paths(home, "*/*/summary.json", result, boundary=self.root.path),
        ):
            if session is None:
                result.complete, result.reason = False, "invalid_native_record"
            else:
                result.sessions.append(session)
        return result

    def _discover_one(self, marker):
        try:
            row = json_file(marker)
            info = row.get("info", {})
            if not isinstance(info, dict):
                raise Failure("unsupported_native_schema", 3)
            native = info.get("id")
            if not isinstance(native, str) or native != marker.parent.name:
                raise Failure("unsupported_native_schema", 3)

            def get(key, row=row, info=info):
                return row.get(key, info.get(key))

            inventory, known_bytes = directory_inventory(marker.parent)
            session = Session.build(
                self.root,
                native,
                marker.parent,
                cwd=info.get("cwd"),
                title=get("generated_title"),
                preview=get("session_summary"),
                model=get("current_model_id"),
                created_at=timestamp(get("created_at")),
                last_activity_at=timestamp(get("last_active_at") or get("updated_at")),
                profile=self.profile,
                fingerprint=inventory,
                known_bytes=known_bytes,
            )
            session.capabilities["metadata"] = Capability("supported")
            annotate_dates(
                session, [get("created_at")], [get("last_active_at") or get("updated_at")]
            )
            session.capabilities["resume"] = resume_capability(self.root)
            return session
        except (Failure, OSError):
            return None

    def read_history(self, session):
        import hashlib
        import json
        from pathlib import Path

        from ..models import HistoryEvent, HistoryResult, identity
        from .base import json_lines
        from .jsonl_cursor import project

        path = Path(session.locator)
        events = {}
        packets = {}
        state = "complete"
        previous = None
        summary = json_file(path / "summary.json")
        version = summary.get(
            "chat_format_version", summary.get("info", {}).get("chat_format_version")
        )
        if version not in (0, 1, None):
            return HistoryResult([], "unavailable", "unknown_chat_format")
        updates = path / "updates.jsonl"
        if not updates.exists():
            return self._raw_history(session, path / "chat_history.jsonl")
        try:
            for ordinal, row in json_lines(updates, cache=getattr(self, "jsonl_cache", None)):
                params = row.get("params", {})
                if params.get("sessionId") not in (None, session.native_id):
                    state = "partial"
                    continue
                update = params.get("update", {})
                kind = update.get("sessionUpdate")
                meta = {**params.get("_meta", {}), **update.get("_meta", {})}
                event_id = meta.get("eventId")
                if isinstance(event_id, str) and event_id:
                    signature = hashlib.sha256(
                        json.dumps(project(params), sort_keys=True).encode()
                    ).hexdigest()
                    if event_id in packets:
                        if packets[event_id] != signature:
                            state = "partial"
                        continue
                    packets[event_id] = signature
                message_id = update.get("messageId") or meta.get("messageId")
                prompt_id = meta.get("promptId")
                if kind in ("tool_call", "tool_call_update"):
                    previous = None
                    tool_id = update.get("toolCallId")
                    if not isinstance(tool_id, str):
                        state = "partial"
                        continue
                    key = "tool:" + tool_id
                    if key not in events:
                        events[key] = HistoryEvent(
                            identity(session.namespace_id, session.native_id, key),
                            "tool_call",
                            ordinal,
                            text=update.get("title")
                            if isinstance(update.get("title"), str)
                            else "Tool call",
                            native_id=tool_id,
                        )
                    status = update.get("status")
                    if isinstance(status, str):
                        events[key].payload["status"] = status
                    if status in ("completed", "failed"):
                        pieces = []
                        for block in update.get("content", []):
                            nested = block.get("content", {})
                            if nested.get("type") == "text" and isinstance(nested.get("text"), str):
                                pieces.append(nested["text"])
                        result_key = "result:" + tool_id
                        events[result_key] = HistoryEvent(
                            identity(session.namespace_id, session.native_id, result_key),
                            "tool_result",
                            ordinal,
                            text="\n".join(pieces) or None,
                            native_id=tool_id,
                            payload={"status": status},
                        )
                    continue
                if kind not in ("user_message_chunk", "agent_message_chunk"):
                    if kind not in (
                        "session_info_update",
                        "current_mode_update",
                        "available_commands_update",
                        "usage_update",
                        "agent_thought_chunk",
                    ):
                        state = "partial"
                    continue
                role = "user" if kind == "user_message_chunk" else "assistant"
                content = update.get("content", {})
                if content.get("type") != "text" or not isinstance(content.get("text"), str):
                    state = "partial"
                    continue
                scoped = message_id or (
                    "prompt:" + prompt_id
                    if role == "assistant" and isinstance(prompt_id, str)
                    else None
                )
                key = scoped or event_id
                if not isinstance(key, str):
                    key = "ordinal:" + str(ordinal)
                    state = "partial"
                if scoped is None and previous and previous[0] == role:
                    # Contiguous chunks without a message/prompt identity are readable,
                    # but cannot prove separate native message boundaries.
                    key = previous[1]
                    state = "partial"
                if key in events:
                    events[key].text += content["text"]
                else:
                    events[key] = HistoryEvent(
                        identity(session.namespace_id, session.native_id, key),
                        role,
                        ordinal,
                        text=content["text"],
                        timestamp=timestamp(meta.get("agentTimestampMs"), milliseconds=True)
                        or timestamp(row.get("timestamp")),
                        native_id=key,
                        turn_id=prompt_id if isinstance(prompt_id, str) else None,
                    )
                previous = (role, key)
        except (OSError, Failure, ValueError, TypeError, AttributeError):
            state = "partial"
        if not events and state == "complete" and (path / "chat_history.jsonl").exists():
            return self._raw_history(session, path / "chat_history.jsonl")
        return HistoryResult(
            list(events.values()), state, None if state == "complete" else "history_incomplete"
        )

    def _raw_history(self, session, path):
        from ..models import HistoryEvent, HistoryResult, identity
        from .base import json_lines

        if not path.exists():
            return HistoryResult([], "unavailable", "history_not_recorded")
        events = []
        state = "complete"
        try:
            for ordinal, row in json_lines(path, cache=getattr(self, "jsonl_cache", None)):
                role = row.get("role") or row.get("type")
                if role == "system":
                    continue
                if role not in ("user", "assistant", "tool", "tool_result"):
                    state = "partial"
                    continue
                content = row.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "\n".join(
                        block["text"]
                        for block in content
                        if isinstance(block, dict)
                        and block.get("type") in ("text", "input_text")
                        and isinstance(block.get("text"), str)
                    )
                else:
                    text = None
                    state = "partial"
                native = row.get("id") if isinstance(row.get("id"), str) else "raw:" + str(ordinal)
                mapped = "tool_result" if role in ("tool", "tool_result") else role
                events.append(
                    HistoryEvent(
                        identity(session.namespace_id, session.native_id, native),
                        mapped,
                        len(events),
                        text=text,
                        native_id=native,
                        locator=str(path),
                    )
                )
        except (Failure, OSError, ValueError):
            state = "partial"
        return HistoryResult(events, state, None if state == "complete" else "history_incomplete")

    def prepare_cleanup_bundle(self, session):
        from .base import prepare_cleanup_bundle

        return prepare_cleanup_bundle(self.root, session)

    def read_usage(self, session):
        from pathlib import Path

        from ..models import UsageResult, UsageSnapshot
        from .base import usage_counts

        path = Path(session.locator) / "usage.json"
        if not path.exists():
            return UsageResult(state="unavailable", reason="not_recorded")
        try:
            raw = json_file(path)
            if raw.get("sessionId") not in (None, session.native_id):
                return UsageResult(state="partial", reason="usage_identity_mismatch")
            totals = raw.get("session", raw)
            if not isinstance(totals, dict):
                return UsageResult(state="partial", reason="invalid_usage")
            mapping = {
                "input_tokens": "inputTokens",
                "output_tokens": "outputTokens",
                "cache_read_tokens": "cachedReadTokens",
                "cache_write_tokens": "cacheCreationTokens",
                "reasoning_tokens": "reasoningTokens",
                "total_tokens": "totalTokens",
            }
            values = usage_counts(totals, mapping)
            if all(value is None for value in values.values()):
                return UsageResult(state="unavailable", reason="unsupported_usage_schema")
            state = (
                "partial"
                if raw.get("usageIsIncomplete") or totals.get("usageIsIncomplete")
                else "complete"
            )
            snapshot = UsageSnapshot(
                session.session_uid,
                "grok-session:" + session.native_id,
                "current",
                values,
                completeness=state,
                native_revision={
                    **fingerprint(path),
                    "cost_is_partial": bool(raw.get("costIsPartial")),
                },
            )
            return UsageResult([], [snapshot], [], state)
        except (Failure, ValueError):
            return UsageResult(state="partial", reason="invalid_usage")
