"""Selected lifetime histories: unique facts, explicit snapshot and unknown coverage."""

from __future__ import annotations

import datetime as dt
import json

from .catalog import unpack
from .models import TOKEN_CATEGORIES, Failure
from .search import local_zone


def _token_metrics(sessions, facts, members, snapshots, *, allowed=None, allow_snapshots=True):
    ids = {s.session_uid for s in sessions}
    chosen = [
        f
        for f in facts
        if members.get(f.fact_uid, set()) & ids and (allowed is None or f.fact_uid in allowed)
    ]
    relevant = [s for s in snapshots if s.session_uid in ids] if allow_snapshots else []
    included = [
        s for s in relevant if s.summability == "disjoint" or (len(ids) == 1 and len(relevant) == 1)
    ]
    excluded = [s for s in relevant if s not in included]
    covered = {uid for snapshot in included for uid in snapshot.covered_fact_ids}
    # A snapshot without a proven covered set cannot be added to receipts for that scope.
    for snapshot in list(included):
        if not snapshot.covered_fact_ids and any(
            snapshot.session_uid in members.get(f.fact_uid, set()) for f in chosen
        ):
            included.remove(snapshot)
            excluded.append(snapshot)
    chosen = [f for f in chosen if f.fact_uid not in covered]
    own_facts = {uid: [] for uid in ids}
    for fact in facts:
        for uid in members.get(fact.fact_uid, set()) & ids:
            own_facts[uid].append(fact)
    own_scopes = {uid: [] for uid in ids}
    for snapshot in relevant:
        own_scopes[snapshot.session_uid].append(snapshot)
    excluded_sessions = {snapshot.session_uid for snapshot in excluded}
    result = {}
    for category in TOKEN_CATEGORIES:
        values = [getattr(f, category) for f in chosen if getattr(f, category) is not None]
        values.extend(s.values[category] for s in included if s.values[category] is not None)
        known = set()
        incomplete = set()
        for session in sessions:
            uid = session.session_uid
            own = own_facts[uid]
            own_snapshots = own_scopes[uid]
            if any(getattr(f, category) is not None for f in own) or any(
                s.values[category] is not None for s in own_snapshots
            ):
                known.add(uid)
            if (
                uid not in known
                or session.usage_state != "complete"
                or any(f.completeness != "complete" or getattr(f, category) is None for f in own)
                or any(s.completeness != "complete" for s in own_snapshots)
                or uid in excluded_sessions
            ):
                incomplete.add(uid)
        complete = not incomplete and not excluded
        value = (
            sum(values)
            if values
            else 0
            if not ids or (allowed is not None and known and not excluded)
            else None
        )
        reason = (
            None
            if complete
            else "non_summable"
            if excluded
            else "not_recorded"
            if value is None
            else "partial_coverage"
        )
        result[category] = {
            "value": value,
            "reason": reason,
            "complete": complete,
            "selected_sessions": len(ids),
            "known_sessions": len(known),
            "incomplete_sessions": len(incomplete),
            "known_fact_count": sum(getattr(f, category) is not None for f in chosen),
            "included_snapshot_scopes": [
                s.accounting_scope for s in included if s.values[category] is not None
            ],
            "excluded_snapshot_scopes": [s.accounting_scope for s in excluded],
        }
    return result


def _other_metrics(catalog, sessions):
    ids = [s.session_uid for s in sessions]
    events = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for row in catalog.connection.execute(
            f"SELECT e.event_uid,e.payload,m.uid FROM events e JOIN event_memberships m USING(event_uid) WHERE m.uid IN ({marks})",
            ids,
        ):
            event = json.loads(unpack(row["payload"]))
            events.setdefault(event["role"], set()).add(event["event_uid"])
    messages = events.get("user", set()) | events.get("assistant", set())
    tools = events.get("tool_call", set()) | events.get("tool_result", set())
    history_known = sum(s.history_state == "complete" for s in sessions)
    known_bytes = [s.known_bytes for s in sessions if s.known_bytes is not None]
    created = [s.created_at for s in sessions if s.created_at is not None]
    last = [s.last_activity_at for s in sessions if s.last_activity_at is not None]

    def metric(value, known, complete, reason=None):
        return {
            "value": value,
            "known_sessions": known,
            "selected_sessions": len(sessions),
            "complete": complete,
            "reason": None if complete else reason or "partial_coverage",
        }

    return {
        "messages": metric(
            len(messages) if messages or history_known or not sessions else None,
            history_known,
            history_known == len(sessions),
            "history_incomplete",
        ),
        "tool_events": metric(
            len(tools) if history_known or tools or not sessions else None,
            history_known,
            history_known == len(sessions),
            "history_incomplete",
        ),
        "known_session_bytes": metric(
            sum(known_bytes) if known_bytes or not sessions else None,
            len(known_bytes),
            len(known_bytes) == len(sessions),
            "shared_or_unknown_bytes",
        ),
        "elapsed_span_ms": metric(
            max(0, max(last) - min(created)) if created and last else None,
            sum(s.created_at is not None and s.last_activity_at is not None for s in sessions),
            len(created) == len(last) == len(sessions),
            "elapsed_span_is_not_active_time",
        ),
    }


def summarize(catalog, sessions, *, group_by=None, selection=None):
    if group_by not in (None, "source", "project", "day"):
        raise Failure("invalid_group_by", 2)
    facts, members, snapshots = catalog.usage([s.session_uid for s in sessions])
    metrics = _token_metrics(sessions, facts, members, snapshots)
    metrics.update(_other_metrics(catalog, sessions))
    groups = []
    if group_by:

        def group_key(session):
            if group_by == "source":
                return session.provider
            if group_by == "project":
                return session.cwd or "unknown"
            return (
                dt.datetime.fromtimestamp(session.last_activity_at / 1000, local_zone())
                .date()
                .isoformat()
                if session.last_activity_at is not None
                else "unknown"
            )

        mapping = {s.session_uid: group_key(s) for s in sessions}
        shared = {
            f.fact_uid
            for f in facts
            if len({mapping[uid] for uid in members.get(f.fact_uid, set()) if uid in mapping}) > 1
        }
        for key in sorted(set(mapping.values())):
            selected = [s for s in sessions if mapping[s.session_uid] == key]
            values = _token_metrics(
                selected, facts, members, snapshots, allowed={f.fact_uid for f in facts} - shared
            )
            values.update(_other_metrics(catalog, selected))
            groups.append({"key": key, "session_count": len(selected), "metrics": values})
        if shared:
            selected = [
                s
                for s in sessions
                if any(s.session_uid in members.get(uid, set()) for uid in shared)
            ]
            groups.append(
                {
                    "key": "shared_usage",
                    "session_count": len(selected),
                    "metrics": _token_metrics(
                        selected, facts, members, [], allowed=shared, allow_snapshots=False
                    ),
                }
            )
    contexts = []
    for session in sessions:
        row = catalog.connection.execute(
            "SELECT payload FROM context_metrics WHERE uid=?", (session.session_uid,)
        ).fetchone()
        if row:
            contexts.extend(json.loads(row[0]))
    return {
        "scope": "selected_session_lifetimes",
        "selection": selection
        if selection is not None
        else {"session_ids": [s.display_id for s in sessions], "scope": "explicit_sessions"},
        "activity_range": {
            "started_at": min(
                (
                    s.created_at
                    for s in sessions
                    if s.created_at is not None and s.timezone_confidence == "known"
                ),
                default=None,
            ),
            "last_activity_at": max(
                (
                    s.last_activity_at
                    for s in sessions
                    if s.last_activity_at is not None and s.timezone_confidence == "known"
                ),
                default=None,
            ),
            "complete": all(
                s.created_at is not None
                and s.last_activity_at is not None
                and s.timezone_confidence == "known"
                for s in sessions
            ),
            "time_zone": "UTC",
        },
        "accounting_mode": "unique_fact_union",
        "period_semantics": "sessions_selected_by_last_activity",
        "time_zone": str(local_zone()),
        "metrics": metrics,
        "groups": groups,
        "context_metrics": contexts,
        "coverage": {
            "selected_sessions": len(sessions),
            "categories": {k: metrics[k] for k in TOKEN_CATEGORIES},
        },
        "notes": [
            "Unknown lifetime usage is not zero. Context occupancy is separate.",
            "Overlapping groups are not summed; shared request facts have a shared_usage bucket.",
            "Elapsed span is wall-clock range, not active working hours.",
        ],
    }
