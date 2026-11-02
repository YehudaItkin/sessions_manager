from sessions_manager.models import SourceRoot
from sessions_manager.sources.codex import Adapter
from tests.support.codex_factory import make


def test_catalog_without_rollout_still_discovered(tmp_path):
    make(tmp_path, rollout=False)
    result = Adapter(SourceRoot.create("codex", tmp_path)).discover()
    assert result.complete
    session = result.sessions[0]
    assert session.native_id == "codex-one"
    assert session.created_at == 1767225600123
    assert session.capabilities["cleanup"].reason == "native_cascade_unbounded"
    assert session.capabilities["resume"].state == "unavailable"
