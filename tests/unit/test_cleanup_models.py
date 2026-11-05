import pytest

from sessions_manager.models import OperationItem, OperationPlan, TrashEntry


def test_action_and_payload_identity_validation():
    with pytest.raises(ValueError):
        OperationPlan("plan", "remove_all", [], [], 0, True, 0, 1000, "digest")
    with pytest.raises(ValueError):
        TrashEntry("../escape", "session", "op", {}, "profile", 0, [])


@pytest.mark.parametrize(
    "values",
    [{"action": "remove_all"}, {"state": "done"}, {"updated_at": True}, {"operation_id": ""}],
)
def test_operation_item_validates_boundary_fields(values):
    args = {"operation_id": "op", "target_id": "session", "action": "trash"} | values
    with pytest.raises(ValueError):
        OperationItem(**args)
