import pytest

from sessions_manager.models import HistoryEvent, HistoryResult


def test_roles_and_unknown_history():
    event = HistoryEvent("event", "user", 0, text="literal")
    assert event.text == "literal"
    with pytest.raises(ValueError):
        HistoryEvent("bad", "admin", 0)
    assert HistoryResult([], state="unavailable").state != "complete"
