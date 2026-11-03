import json

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


@pytest.mark.parametrize("version", ["2.2.1", "3.0.0", "2.1.999", "unknown"])
def test_unverified_transcript_version_still_blocks_cleanup(tmp_path, version):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        path.write_text(path.read_text().replace("2.1.263", version))
        before = path.read_bytes()
        with pytest.raises(Failure, match="cleanup_profile_unverified"):
            service.preview("trash", [uid])
        assert path.read_bytes() == before


def test_closed_session_workflows_move_and_restore_without_touching_script_source(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        workflows = path.with_suffix("") / "workflows"
        workflows.mkdir(parents=True)
        shared_script = tmp_path / "project-script.js"
        shared_script.write_text("throw new Error('MUST NEVER EXECUTE')")
        (workflows / "run-one.js").write_bytes(shared_script.read_bytes())
        (workflows / "run-one.json").write_text(
            json.dumps(
                {
                    "runId": "run-one",
                    "status": "completed",
                    "scriptPath": str(shared_script),
                    "phases": [],
                    "result": {},
                }
            )
        )
        before = tree_bytes(workflows)
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert not workflows.exists() and neighbor.exists() and shared_script.exists()
        trash = result["items"][0]["trash_id"]
        restore = service.preview("restore", [trash])
        service.commit("restore", [trash], restore["confirmation_token"])
        assert tree_bytes(workflows) == before


def test_workflow_local_script_path_can_differ_from_run_id(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        workflows = path.with_suffix("") / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "scripts").mkdir()
        script = workflows / "scripts" / "source-copy.js"
        script.write_text("throw new Error('never execute')")
        (workflows / "run-one.json").write_text(
            json.dumps(
                {"runId": "run-one", "status": "completed", "phases": [], "scriptPath": str(script)}
            )
        )
        assert service.preview("trash", [uid])["targets"]


@pytest.mark.parametrize(
    "record",
    [
        {"runId": "wrong", "status": "completed", "phases": []},
        {"runId": "run-one", "status": "running", "phases": []},
    ],
)
def test_unproven_or_running_workflow_is_not_removed(tmp_path, record):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        workflows = path.with_suffix("") / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "run-one.json").write_text(json.dumps(record))
        before = tree_bytes(workflows)
        with pytest.raises(
            Failure,
            match="workflow_not_closed"
            if record["status"] == "running"
            else "unknown_bundle_topology",
        ):
            service.preview("trash", [uid])
        assert tree_bytes(workflows) == before and path.exists()
