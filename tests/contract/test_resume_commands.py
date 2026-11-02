from pathlib import Path

import pytest

from sessions_manager.discovery import adapter
from sessions_manager.launch import build_request
from sessions_manager.models import Failure, SourceRoot
from tests.support import claude_factory, codex_factory, cursor_factory, grok_factory


@pytest.mark.parametrize("provider", ["codex", "claude", "grok", "cursor"])
def test_exact_argv_and_independent_history_binding(tmp_path, fake_executable, provider):
    native = tmp_path / provider
    cwd = tmp_path / "original"
    factory = {
        "codex": codex_factory,
        "claude": claude_factory,
        "grok": grok_factory,
        "cursor": cursor_factory,
    }[provider]
    path = factory.make(native, cwd=cwd)
    root = SourceRoot.create(
        provider,
        native,
        resume_context="native",
        executable_path=fake_executable,
        executable_version="synthetic",
    )
    session = adapter(root).discover().sessions[0]
    request = build_request(root, session, tmp_path / "data")
    expected = {
        "codex": ["resume", session.native_id, "-C", str(cwd)],
        "claude": ["--resume", session.native_id],
        "grok": ["--cwd", str(cwd), "--resume", session.native_id],
        "cursor": ["--workspace", str(cwd), "--resume", session.native_id],
    }
    assert request.argv == [str(fake_executable), *expected[provider]]
    # Independent source resolver: the request's immutable locator still selects
    # the original fixture in its native namespace, rather than any new workspace.
    assert request.history_locator["path"] == str(path)
    assert request.history_locator["native_id"] == session.native_id
    assert request.cwd == str(cwd)
    from tests.support.native_resolver import resolve

    selected_home = Path(
        request.context_overrides.get("CODEX_HOME")
        or request.context_overrides.get("CLAUDE_CONFIG_DIR")
        or native
    )
    assert resolve(provider, request.argv, request.cwd, selected_home) == path
    other = tmp_path / "moved"
    other.mkdir()
    with pytest.raises(Failure) as caught:
        build_request(root, session, tmp_path / "data", cwd=other)
    assert caught.value.exit_code == 4
    guide = caught.value.data["manual_resume_guide"]
    assert guide["history_locator"]["path"] == str(path)
    assert guide["options"] == ["choose_cwd", "cancel"]
    assert guide["help_argv"] == [str(fake_executable), "--help"]
    assert not (tmp_path / "data/launches").exists()


def test_cli_resume_dry_run_and_manual_guide(isolated, tmp_path, fake_executable):
    import json

    from typer.testing import CliRunner

    from sessions_manager.cli import app
    from tests.support.claude_factory import make

    config, data = isolated
    root = tmp_path / "native"
    make(root)
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\nresume_context="native"\npath='
        + repr(str(root))
        + "\nexecutable="
        + repr(str(fake_executable))
        + "\n"
    )
    base = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    runner = CliRunner()
    rows = runner.invoke(app, [*base, "list"])
    uid = json.loads(rows.stdout)["data"]["items"][0]["display_id"]
    result = runner.invoke(app, [*base, "resume", uid, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["argv"][1:] == ["--resume", "claude-one"]
    moved = tmp_path / "moved"
    moved.mkdir()
    result = runner.invoke(app, [*base, "resume", uid, "--cwd", str(moved)])
    assert result.exit_code == 4, result.output
    assert (
        json.loads(result.stdout)["data"]["manual_resume_guide"]["reason"]
        == "resume_cwd_unsupported"
    )
    assert not list((data / "launches").glob("*.json"))


@pytest.mark.parametrize("provider", ["grok", "cursor"])
def test_custom_native_home_without_supported_context_override_is_view_only(
    tmp_path, fake_executable, provider
):
    factory = grok_factory if provider == "grok" else cursor_factory
    factory.make(tmp_path / provider)
    root = SourceRoot.create(
        provider,
        tmp_path / provider,
        root_kind="explicit",
        resume_context="native",
        executable_path=fake_executable,
    )
    session = adapter(root).discover().sessions[0]
    with pytest.raises(Failure, match="resume_binding_unverified"):
        build_request(root, session, tmp_path / "manager")
