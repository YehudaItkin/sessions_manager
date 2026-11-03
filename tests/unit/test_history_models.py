import pytest

from sessions_manager.models import HistoryEvent, HistoryResult


def test_roles_and_unknown_history():
    event = HistoryEvent("event", "user", 0, text="literal")
    assert event.text == "literal"
    with pytest.raises(ValueError):
        HistoryEvent("bad", "admin", 0)
    assert HistoryResult([], state="unavailable").state != "complete"


def test_normalized_history_text_rejects_structured_payloads():
    import pytest

    from sessions_manager.models import HistoryEvent

    with pytest.raises(ValueError):
        HistoryEvent("event", "tool_result", 1, text=[{"type": "input_text", "text": "synthetic"}])
