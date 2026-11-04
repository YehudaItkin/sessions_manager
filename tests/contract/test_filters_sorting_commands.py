import json

import pytest
import tomli_w
from typer.testing import CliRunner

from sessions_manager.cli import app
from tests.support.claude_factory import make
from tests.support.grok_factory import make as grok


def prepare(isolated, tmp_path):
    config, data = isolated
    claude = tmp_path / "claude"
    for native in ("Alpha", "zeta", "excluded"):
        path = make(claude, native, cwd=tmp_path / "My Project", message_id=native)
        if native == "excluded":
            path.write_text(
                path.read_text().replace('"model": "synthetic"', '"model": "other-model"')
            )
    grok(tmp_path / "grok", "B", cwd=tmp_path / "My Project")
    config.write_text(
        tomli_w.dumps(
            {
                "discovery_roots_mode": "replace",
                "sources": [
                    {"provider": "claude", "path": str(claude)},
                    {"provider": "grok", "path": str(tmp_path / "grok")},
                ],
            }
        )
    )
    return ["--config", str(config), "--data-dir", str(data), "--format", "json"]


@pytest.mark.parametrize("command", ["list", "refresh"])
def test_combined_cli_filters_and_whole_selection_sort(isolated, tmp_path, command):
    base = prepare(isolated, tmp_path)
    result = CliRunner().invoke(
        app,
        [
            *base,
            command,
            "--source",
            "claude",
            "--source",
            "grok",
            "--project",
            "my project",
            "--model",
            "SYNTH",
            "--activity",
            "unknown",
            "--since",
            "2026-01-01T00:00:00Z",
            "--until",
            "2026-01-01T00:00:01Z",
            "--sort",
            "id",
            "--order",
            "desc",
        ],
    )
    assert result.exit_code == 0, result.output
    assert [s["native_id"] for s in json.loads(result.stdout)["data"]["items"]] == [
        "zeta",
        "B",
        "Alpha",
    ]
    if command == "list":
        result = CliRunner().invoke(
            app,
            [
                *base,
                "list",
                "--model",
                "synthetic",
                "--sort",
                "id",
                "--order",
                "desc",
                "--limit",
                "1",
                "--offset",
                "1",
            ],
        )
        data = json.loads(result.stdout)["data"]
        assert data["total"] == 3 and data["items"][0]["native_id"] == "B"


def test_stats_uses_same_model_activity_selection(isolated, tmp_path):
    base = prepare(isolated, tmp_path)
    result = CliRunner().invoke(
        app, [*base, "stats", "--source", "claude", "--model", "SYNTH", "--activity", "unknown"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["coverage"]["selected_sessions"] == 2


def test_model_filter_does_not_narrow_refresh_or_change_native_bytes(isolated, tmp_path):
    from sessions_manager.catalog import Catalog

    base = prepare(isolated, tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, [*base, "refresh"]).exit_code == 0
    other = tmp_path / "claude/projects/encoded-is-not-cwd/excluded.jsonl"
    other.write_text(
        other.read_text().replace("Synthetic Claude question", "updated outside displayed model")
    )
    paths = [p for root in ("claude", "grok") for p in (tmp_path / root).rglob("*") if p.is_file()]
    before = {p: p.read_bytes() for p in paths}
    result = runner.invoke(
        app,
        [*base, "refresh", "--source", "claude", "--model", "synthetic", "--activity", "unknown"],
    )
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["data"]["items"]) == 2
    with Catalog(isolated[1]) as catalog:
        assert (
            next(s for s in catalog.sessions() if s.native_id == "excluded").preview
            == "updated outside displayed model"
        )
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("command", ["list", "refresh", "stats"])
def test_invalid_filter_is_rejected_without_catalog_or_scan(isolated, command):
    config, data = isolated
    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config),
            "--data-dir",
            str(data),
            "--format",
            "json",
            command,
            "--activity",
            "running",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_query"
    assert not data.exists()
