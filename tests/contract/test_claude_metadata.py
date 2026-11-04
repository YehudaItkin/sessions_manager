from sessions_manager.models import SourceRoot
from sessions_manager.sources.claude import Adapter
from tests.support.claude_factory import make


def test_metadata_not_directory_decoding(tmp_path):
    cwd = tmp_path / "real project"
    make(tmp_path, cwd=cwd)
    result = Adapter(SourceRoot.create("claude", tmp_path)).discover()
    assert result.complete
    session = result.sessions[0]
    assert session.cwd == str(cwd)
    assert session.native_id == "claude-one"
    assert session.capabilities["resume"].state == "unavailable"
    assert session.last_activity_at == 1767225601000


def test_model_is_last_recorded_assistant_model_not_user_metadata(tmp_path):
    import json

    from tests.support.claude_factory import make

    path = make(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["message"]["model"] = "not-an-assistant-model"
    rows.append(
        {
            **rows[1],
            "uuid": "next",
            "message": {**rows[1]["message"], "model": "new-synthetic-model"},
        }
    )
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = Adapter(SourceRoot.create("claude", tmp_path)).discover()
    assert result.sessions[0].model == "new-synthetic-model"
