import pytest

from sessions_manager.models import UsageFact, UsageSnapshot


def test_nullable_counts_and_snapshot_summability():
    assert UsageFact("f", "claude", "profile", "request", input_tokens=0).input_tokens == 0
    for value in (True, -1, "10"):
        with pytest.raises(ValueError):
            UsageFact("f", "claude", "profile", "request", input_tokens=value)
    with pytest.raises(ValueError):
        UsageSnapshot("session", "scope", "epoch", {}, summability="guess")
