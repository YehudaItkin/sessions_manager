import pytest

from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


def test_codex_unavailable_and_unknown_requires_assertion(tmp_path):
    with case(tmp_path / "codex", "codex") as (service, root, uid, path, neighbor):
        with pytest.raises(Failure, match="native_cascade_unbounded"):
            service.preview("trash", [uid])
    with case(tmp_path / "claude") as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        before = tree_bytes(root.path)
        with pytest.raises(Failure) as error:
            service.commit("trash", [uid], plan["confirmation_token"])
        assert error.value.exit_code == 7
        assert tree_bytes(root.path) == before
        with pytest.raises(Failure):
            service.commit("purge", [uid], plan["confirmation_token"], assert_closed=True)
        assert tree_bytes(root.path) == before


def test_expiry_and_changed_source_never_mutate(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        service.catalog.connection.execute("UPDATE operation_plans SET expires_at=0")
        service.catalog.connection.commit()
        with pytest.raises(Failure, match="confirmation_expired"):
            service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        plan = service.preview("trash", [uid])
        path.write_text(path.read_text() + "\n")
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "failed_no_change"
        assert path.exists()
