import pytest

from sessions_manager.models import OperationPlan, TrashEntry


def test_action_and_payload_identity_validation():
    with pytest.raises(ValueError):
        OperationPlan("plan", "remove_all", [], [], 0, True, 0, 1000, "digest")
    with pytest.raises(ValueError):
        TrashEntry("../escape", "session", "op", {}, "profile", 0, [])
