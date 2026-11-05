import pytest

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


@pytest.mark.parametrize("used,maximum", [(0, 120000), (42, 120000), (None, 120000), (42, None)])
def test_proven_conversation_token_details_are_context_only(tmp_path, used, maximum):
    make(tmp_path, context=(used, maximum))
    adapter = Adapter(SourceRoot.create("cursor", tmp_path))
    session = adapter.discover().sessions[0]
    usage = adapter.read_usage(session)
    assert usage.state == "unavailable" and usage.reason == "not_recorded"
    assert not usage.facts and not usage.snapshots
    assert len(usage.context_metrics) == 1
    context = usage.context_metrics[0]
    assert context.kind == "context"
    assert context.used_tokens == used and context.max_tokens == maximum
    assert context.native_revision["root_blob_id"] == "root"
    assert context.source_profile == adapter.profile


@pytest.mark.parametrize("details", [b"\x0a\x01x", b"\x08\x01\x08\x02", b"\x08\xff"])
def test_malformed_or_unknown_context_never_becomes_lifetime_zero(tmp_path, details):
    import sqlite3

    from tests.support.cursor_factory import wire

    path = make(tmp_path)
    with sqlite3.connect(path / "store.db") as db:
        db.execute("UPDATE blobs SET data=? WHERE id='root'", (wire(8, "turn") + wire(5, details),))
    adapter = Adapter(SourceRoot.create("cursor", tmp_path))
    usage = adapter.read_usage(adapter.discover().sessions[0])
    assert not usage.context_metrics and not usage.facts and not usage.snapshots
    assert usage.state == "unavailable"


def test_human_stats_exposes_context_without_lifetime_estimate(isolated, tmp_path):
    from typer.testing import CliRunner

    from sessions_manager.cli import app

    config, data = isolated
    make(tmp_path / "native", context=(0, 120000))
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="cursor"\npath='
        + repr(str(tmp_path / "native"))
        + "\n"
    )
    result = CliRunner().invoke(app, ["--config", str(config), "--data-dir", str(data), "stats"])
    assert result.exit_code == 0, result.output
    assert "Context occupancy" in result.output and "0 / 120000" in result.output
    assert "unknown" in result.output
