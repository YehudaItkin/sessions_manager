from sessions_manager.models import SourceRoot
from sessions_manager.sources.cursor import Adapter
from tests.support.cursor_factory import make


def test_no_lifetime_ledger_is_unknown_not_zero(tmp_path):
    make(tmp_path)
    adapter = Adapter(SourceRoot.create("cursor", tmp_path))
    session = adapter.discover().sessions[0]
    usage = adapter.read_usage(session)
    assert usage.facts == [] and usage.snapshots == []
    assert usage.state == "unavailable"
    assert usage.reason == "not_recorded"
