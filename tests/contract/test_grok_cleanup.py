import pytest

from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


def test_grok_local_directory_only(tmp_path):
    with case(tmp_path, "grok") as (service, root, uid, path, neighbor):
        before = tree_bytes(neighbor)
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "trashed"
        assert not path.exists() and tree_bytes(neighbor) == before


def test_unknown_shared_search_dependency_disables_cleanup(tmp_path):
    with case(tmp_path, "grok") as (service, root, uid, path, neighbor):
        (root.path / "sessions/search.db").write_text("unknown shared index")
        with pytest.raises(Failure, match="shared_dependency_unverified"):
            service.preview("trash", [uid])
