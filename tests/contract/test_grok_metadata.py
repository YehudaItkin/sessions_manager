from sessions_manager.models import SourceRoot
from sessions_manager.sources.grok import Adapter
from tests.support.grok_factory import make


def test_only_summary_backed_native_sessions(tmp_path):
    make(tmp_path)
    (tmp_path / "sessions/encoded/images-only/images").mkdir(parents=True)
    (tmp_path / "grok.db").write_text("unattributed format")
    result = Adapter(SourceRoot.create("grok", tmp_path)).discover()
    assert result.complete
    assert [s.native_id for s in result.sessions] == ["grok-one"]
