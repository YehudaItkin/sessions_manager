from ..models import Capability, Failure, Session, timestamp
from .base import ScanResult, fingerprint, json_lines, read_many, resume_context_verified


class Adapter:
    profile = "claude-jsonl-2.1"

    def __init__(self, root):
        self.root = root

    def discover(self):
        result = ScanResult(profile=self.profile)
        if not self.root.path.exists():
            return result
        for session in read_many(
            self._discover_one, sorted((self.root.path / "projects").glob("*/*.jsonl"))
        ):
            if session is None:
                result.complete, result.reason = False, "invalid_native_record"
            else:
                result.sessions.append(session)
        return result

    def _discover_one(self, path):
        try:
            rows = [row for _, row in json_lines(path)]
            native = path.stem
            records = [
                r
                for r in rows
                if r.get("sessionId") == native and r.get("type") in ("user", "assistant")
            ]
            if not records or any(r.get("sessionId") not in (None, native) for r in rows):
                raise Failure("unsupported_native_schema", 3)
            dates = [t for r in records if (t := timestamp(r.get("timestamp"))) is not None]
            cwd = next((r["cwd"] for r in reversed(records) if r.get("cwd")), None)
            first = next(
                (r.get("message", {}).get("content") for r in records if r["type"] == "user"),
                None,
            )
            if isinstance(first, list):
                first = " ".join(b.get("text", "") for b in first if b.get("type") == "text")
            title = next(
                (r.get("title") for r in reversed(rows) if r.get("type") == "ai-title"), None
            )
            session = Session.build(
                self.root,
                native,
                path,
                cwd=cwd,
                title=title,
                preview=first[:500] if isinstance(first, str) else None,
                created_at=min(dates) if dates else None,
                last_activity_at=max(dates) if dates else None,
                profile=self.profile,
                fingerprint=fingerprint(path),
                known_bytes=path.stat().st_size,
            )
            session.capabilities["metadata"] = Capability("supported")
            if resume_context_verified(self.root):
                session.capabilities["resume"] = Capability("supported")
            return session
        except (Failure, OSError, ValueError):
            return None

    def read_history(self, session):
        from pathlib import Path

        from ..models import HistoryEvent, HistoryResult, identity

        events = {}
        state = "complete"
        try:
            for ordinal, row in json_lines(Path(session.locator)):
                kind = row.get("type")
                if kind not in ("user", "assistant"):
                    if kind not in (
                        "system",
                        "attachment",
                        "ai-title",
                        "last-prompt",
                        "agent-name",
                        "mode",
                        "permission-mode",
                        "file-history-snapshot",
                        "file-history-delta",
                        "cost-state",
                        "progress",
                        "queue-operation",
                        "summary",
                    ):
                        state = "partial"
                    continue
                message = row.get("message", {})
                native = message.get("id") if kind == "assistant" else row.get("uuid")
                if not native:
                    state = "partial"
                    continue
                content = message.get("content", [])
                if isinstance(content, str):
                    blocks = [{"type": "text", "text": content}]
                elif isinstance(content, list):
                    blocks = content
                else:
                    state = "partial"
                    continue
                texts = []
                tool_results = []
                tool_calls = []
                for block in blocks:
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        value = block.get("content", "")
                        if isinstance(value, list):
                            value = "\n".join(
                                b.get("text", "") for b in value if b.get("type") == "text"
                            )
                        tool_results.append((block.get("tool_use_id") or native, str(value)))
                    elif block.get("type") == "tool_use":
                        tool_calls.append((block.get("id") or native, block.get("name", "Tool")))
                    elif block.get("type") not in (
                        "thinking",
                        "redacted_thinking",
                        "image",
                        "document",
                    ):
                        state = "partial"
                if texts:
                    key = native
                    value = "\n".join(texts)
                    if key in events:
                        previous = events[key]
                        if value.startswith(previous.text or ""):
                            previous.text = value
                        elif previous.text != value:
                            previous.completeness = "partial"
                            state = "partial"
                    else:
                        events[key] = HistoryEvent(
                            identity(session.namespace_id, key),
                            kind,
                            ordinal,
                            text=value,
                            timestamp=timestamp(row.get("timestamp")),
                            native_id=key,
                            parent_id=row.get("parentUuid"),
                            locator=session.locator,
                        )
                for role, entries in (("tool_call", tool_calls), ("tool_result", tool_results)):
                    for key, value in entries:
                        uid = role + ":" + key
                        events[uid] = HistoryEvent(
                            identity(session.namespace_id, uid),
                            role,
                            ordinal,
                            text=value,
                            native_id=key,
                            parent_id=row.get("parentUuid"),
                            locator=session.locator,
                        )
        except (Failure, OSError):
            state = "partial"
        return HistoryResult(sorted(events.values(), key=lambda e: (e.ordinal, e.event_uid)), state)

    def prepare_cleanup_bundle(self, session):
        from .base import prepare_cleanup_bundle

        return prepare_cleanup_bundle(self.root, session)

    def read_usage(self, session):
        from pathlib import Path

        from ..models import TOKEN_CATEGORIES, UsageFact, UsageMembership, UsageResult, identity
        from .base import usage_counts

        facts = {}
        state = "complete"
        mapping = {
            "input_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "cache_read_tokens": "cache_read_input_tokens",
            "cache_write_tokens": "cache_creation_input_tokens",
            "reasoning_tokens": "reasoning_output_tokens",
            "total_tokens": "total_tokens",
        }
        try:
            for _, row in json_lines(Path(session.locator)):
                message = row.get("message", {})
                if row.get("type") != "assistant" or not isinstance(message.get("usage"), dict):
                    continue
                request = message.get("id")
                if not request:
                    state = "partial"
                    continue
                values = usage_counts(message["usage"], mapping, claude=True)
                uid = identity(session.namespace_id, "usage", request)
                fact = UsageFact(
                    uid,
                    "claude",
                    session.namespace_id,
                    request,
                    model=message.get("model"),
                    **values,
                )
                old = facts.get(uid)
                if old and any(
                    getattr(old, key) is not None
                    and (getattr(fact, key) is None or getattr(fact, key) < getattr(old, key))
                    for key in TOKEN_CATEGORIES
                ):
                    old.completeness = "partial"
                    state = "partial"
                else:
                    if old and old.completeness == "partial":
                        fact.completeness = "partial"
                    facts[uid] = fact
        except (OSError, Failure, ValueError):
            state = "partial"
        return UsageResult(
            list(facts.values()),
            [],
            [UsageMembership(session.session_uid, uid) for uid in facts],
            state if facts else "unavailable",
            None if facts else "not_recorded",
        )
