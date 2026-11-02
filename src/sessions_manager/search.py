"""Literal Unicode substring selection; no query text becomes SQL or FTS syntax."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .models import Failure


def local_zone():
    import os
    from pathlib import Path

    name = os.environ.get("TZ")
    if not name:
        try:
            name = str(Path("/etc/localtime").resolve()).split("/zoneinfo/")[1]
        except (OSError, IndexError):
            return dt.datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except (ValueError, KeyError):
        raise Failure("invalid_timezone", 2) from None


def parse_date(value, *, end=False, zone=None):
    if value is None:
        return None
    zone = zone or local_zone()
    try:
        if len(value) == 10:
            date = dt.date.fromisoformat(value)
            parsed = dt.datetime.combine(date, dt.time.max if end else dt.time.min)
        else:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            first, second = parsed.replace(tzinfo=zone, fold=0), parsed.replace(tzinfo=zone, fold=1)
            if first.utcoffset() != second.utcoffset():
                raise Failure("ambiguous_local_time", 2)
            if first.astimezone(dt.UTC).astimezone(zone).replace(tzinfo=None) != parsed:
                raise Failure("nonexistent_local_time", 2)
            parsed = first
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError):
        raise Failure("invalid_date", 2) from None


@dataclass
class QuerySpec:
    providers: list[str] | None = None
    project: str | None = None
    since: str | None = None
    until: str | None = None
    scope: str = "visible"
    sort: str = "recent"
    query: str | None = None

    def filter(self, sessions, catalog=None):
        if self.scope not in ("visible", "hidden", "all") or self.sort not in ("recent", "oldest"):
            raise Failure("invalid_query", 2)
        from .models import PROVIDERS

        if self.providers and any(p not in PROVIDERS for p in self.providers):
            raise Failure("invalid_source", 2)
        lower, upper = parse_date(self.since), parse_date(self.until, end=True)
        if lower is not None and upper is not None and lower > upper:
            raise Failure("invalid_date_range", 2)
        matching = catalog.matching_ids(self.query) if self.query and catalog else None
        rows = [
            s
            for s in sessions
            if (not self.providers or s.provider in self.providers)
            and (not self.project or self.project.casefold() in (s.cwd or "").casefold())
            and (self.scope == "all" or s.hidden == (self.scope == "hidden"))
            and (
                lower is None
                or (
                    s.last_activity_at is not None
                    and s.timezone_confidence == "known"
                    and s.last_activity_at >= lower
                )
            )
            and (
                upper is None
                or (
                    s.last_activity_at is not None
                    and s.timezone_confidence == "known"
                    and s.last_activity_at <= upper
                )
            )
            and (matching is None or s.session_uid in matching)
        ]
        rows.sort(
            key=lambda s: (
                s.last_activity_at is None,
                -(s.last_activity_at or 0) if self.sort == "recent" else s.last_activity_at or 0,
                s.session_uid,
            )
        )
        return rows


def candidate_text(text):
    # Whole logical messages remain in storage. Overlapping windows retain
    # every original trigram; NUL separators cannot create non-NUL short matches.
    if len(text) <= 256:
        return text
    return "\0".join(dict.fromkeys(text[i : i + 258] for i in range(0, len(text), 256)))


def prepare_chunk(kind, text, original_blob=None):
    import zlib

    folded = text.casefold()
    stored = (
        original_blob
        if original_blob is not None and folded == text
        else folded
        if len(folded) <= 256
        else zlib.compress(folded.encode(), 1)
    )
    return kind, stored, candidate_text(folded)
