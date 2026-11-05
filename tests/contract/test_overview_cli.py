import json

from typer.testing import CliRunner

from sessions_manager.cli import app
from tests.support.claude_factory import make


def test_non_tty_list_full_ids_and_no_defaults(isolated, tmp_path):
    config, data = isolated
    root = tmp_path / "native"
    make(root, "very-long-native-id-123456789")
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(root))
        + "\n"
    )
    result = CliRunner().invoke(
        app, ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["data"]["total"] == 1
    session = payload["data"]["items"][0]
    assert session["display_id"].startswith("s-")
    assert session["native_id"] == "very-long-native-id-123456789"


def test_empty_state(isolated):
    config, data = isolated
    result = CliRunner().invoke(
        app, ["--config", str(config), "--data-dir", str(data), "--format", "json", "list"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["total"] == 0


def test_table_output_has_named_id_columns(isolated, tmp_path):
    config, data = isolated
    root = tmp_path / "native"
    make(root)
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(root))
        + "\n"
    )
    result = CliRunner().invoke(app, ["--config", str(config), "--data-dir", str(data), "list"])
    assert result.exit_code == 0, result.output
    assert "Manager ID" in result.output and "Native ID" in result.output
    assert "claude-one" in result.output


def test_handles_are_global_before_pagination_and_hidden_filter(isolated, tmp_path):
    from sessions_manager.catalog import Catalog
    from sessions_manager.models import Session, SourceRoot, short_handles

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(root.path))
        + "\n"
    )
    first = Session.build(root, "one", root.path / "one")
    other = Session.build(root, "two", root.path / "two", hidden=True)
    first.session_uid = "12345678-aaaa-4000-8000-000000000001"
    other.session_uid = "12345678-bbbb-4000-8000-000000000002"
    for session in (first, other):
        session.display_id = "s-" + session.session_uid
    with Catalog(data) as catalog:
        catalog.publish(root, [first, other], complete=True)
        handle = short_handles(catalog.sessions(include_missing=True))[first.session_uid]
        assert catalog.get(handle).session_uid == first.session_uid
    result = CliRunner().invoke(
        app,
        ["--config", str(config), "--data-dir", str(data), "list", "--limit", "1"],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0, result.output
    assert handle in result.output
    assert "Actions" in result.output
    assert "unknown" in result.output


def test_initial_selected_refresh_does_not_touch_other_roots(isolated, tmp_path):
    import tomli_w

    from sessions_manager.catalog import Catalog
    from tests.support.grok_factory import make as grok

    config, data = isolated
    a = tmp_path / "claude"
    b = tmp_path / "grok"
    make(a)
    grok(b)
    config.write_text(
        tomli_w.dumps(
            {
                "discovery_roots_mode": "replace",
                "sources": [
                    {"provider": "claude", "path": str(a)},
                    {"provider": "grok", "path": str(b)},
                ],
            }
        )
    )
    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config),
            "--data-dir",
            str(data),
            "--format",
            "json",
            "refresh",
            "--source",
            "claude",
            "--project",
            "project",
        ],
    )
    assert result.exit_code == 0, result.output
    with Catalog(data) as catalog:
        assert len(catalog.root_states()) == 1
        assert {s.provider for s in catalog.sessions()} == {"claude"}
