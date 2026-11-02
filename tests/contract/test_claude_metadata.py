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
