from zoneinfo import ZoneInfo

import pytest

from sessions_manager.models import Failure, Session, SourceRoot
from sessions_manager.search import QuerySpec, parse_date


def test_inclusive_date_and_dst():
    start = parse_date("2026-01-01", end=False, zone=ZoneInfo("UTC"))
    end = parse_date("2026-01-01", end=True, zone=ZoneInfo("UTC"))
    assert end - start == 86400000 - 1
    with pytest.raises(Failure, match="ambiguous_local_time"):
        parse_date("2026-11-01T01:30:00", zone=ZoneInfo("America/New_York"))


def test_unknown_last_both_directions(tmp_path):
    root = SourceRoot.create("claude", tmp_path)
    rows = [
        Session.build(root, "unknown", tmp_path / "unknown"),
        Session.build(root, "known", tmp_path / "known", last_activity_at=1),
    ]
    assert QuerySpec(sort="recent").filter(rows)[-1].native_id == "unknown"
    assert QuerySpec(sort="oldest").filter(rows)[-1].native_id == "unknown"


def test_candidate_blocks_preserve_every_trigram_without_repeated_pages():
    from sessions_manager.search import candidate_text

    text = "ab" * 10000 + "Z needle" + "ab" * 10000
    reduced = candidate_text(text)
    original_grams = {text[i : i + 3] for i in range(len(text) - 2)}
    reduced_grams = {reduced[i : i + 3] for i in range(len(reduced) - 2)}
    assert original_grams <= reduced_grams
    assert len(reduced) < len(text)
