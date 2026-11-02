import pytest

from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


def test_exact_transcript_and_companion_bundle(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        companion = path.with_suffix("") / "subagents"
        companion.mkdir(parents=True)
        (companion / "agent-one.jsonl").write_text('{"sessionId":"selected","type":"assistant"}\n')
        shared = root.path / "history.jsonl"
        shared.write_text("shared untouched")
        before = tree_bytes(neighbor)
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "trashed"
        assert not path.exists() and not path.with_suffix("").exists()
        assert neighbor.read_bytes() == before
        assert shared.read_text() == "shared untouched"
        trash = result["items"][0]["trash_id"]
        restore = service.preview("restore", [trash])
        service.commit("restore", [trash], restore["confirmation_token"])
        assert path.exists() and (companion / "agent-one.jsonl").exists()


def test_unknown_companion_disables_mutation(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        unknown = path.with_suffix("") / "unknown-shared-link"
        unknown.mkdir(parents=True)
        with pytest.raises(Failure, match="unknown_bundle_topology"):
            service.preview("trash", [uid])
