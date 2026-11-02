import pytest

from sessions_manager.config import Config, ensure_private
from sessions_manager.models import Failure


def test_replace_roots_never_adds_defaults(isolated):
    config, data = isolated
    assert Config.load(config, data).roots == []


def test_standard_roots_have_native_context(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    cfg = Config.load(tmp_path / "absent", tmp_path / "data")
    assert {r.provider for r in cfg.roots} == {"codex", "claude", "grok", "cursor"}
    assert all(r.default_root for r in cfg.roots)


def test_custom_root_is_view_only(isolated, tmp_path):
    path, data = isolated
    path.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(tmp_path / "native"))
        + "\n"
    )
    root = Config.load(path, data).roots[0]
    assert root.resume_context is None
    assert root.namespace_id == "claude:default"


def test_private_mode_and_rejection(tmp_path):
    path = tmp_path / "data"
    ensure_private(path)
    assert path.stat().st_mode & 0o777 == 0o700
    path.chmod(0o755)
    with pytest.raises(Failure, match="unsafe_data_dir"):
        ensure_private(path)
    assert path.stat().st_mode & 0o777 == 0o755


def test_symlink_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(Failure):
        ensure_private(link)


def test_manager_state_cannot_overlap_native_source(tmp_path):
    from sessions_manager.models import SourceRoot

    native = tmp_path / "native"
    native.mkdir()
    cfg = Config(
        native / "manager", tmp_path / "config", [SourceRoot.create("grok", native)], "replace"
    )
    with pytest.raises(Failure, match="data_dir_source_overlap"):
        cfg.prepare()
    assert not cfg.data_dir.exists()
