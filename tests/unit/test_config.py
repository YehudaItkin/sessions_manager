import pytest

from sessions_manager.config import Config, ensure_private
from sessions_manager.models import Failure


@pytest.mark.parametrize("sources", [1, {}, True, ["invalid-source"]])
def test_source_container_shape_is_invalid_config_before_runtime(isolated, sources):
    import tomli_w

    path, data = isolated
    path.write_text(tomli_w.dumps({"discovery_roots_mode": "replace", "sources": sources}))
    with pytest.raises(Failure, match="invalid_config"):
        Config.load(path, data)
    assert not data.exists()


@pytest.mark.parametrize("enabled", ["false", 0])
def test_invalid_enabled_type_is_rejected_before_runtime(isolated, tmp_path, enabled):
    import tomli_w

    path, data = isolated
    path.write_text(
        tomli_w.dumps(
            {
                "discovery_roots_mode": "replace",
                "sources": [
                    {"provider": "claude", "path": str(tmp_path / "source"), "enabled": enabled}
                ],
            }
        )
    )
    with pytest.raises(Failure, match="invalid_config"):
        Config.load(path, data)
    assert not data.exists()


def test_disabled_root_keeps_previous_generation_and_observation(tmp_path):
    import tomli_w

    from sessions_manager.catalog import Catalog
    from sessions_manager.discovery import refresh
    from sessions_manager.models import SourceRoot
    from tests.support.claude_factory import make

    roots = [SourceRoot.create("claude", tmp_path / name, namespace=name) for name in ("a", "b")]
    for root in roots:
        make(root.path)
    cfg = Config(tmp_path / "manager", tmp_path / "config", roots, "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        previous = next(r for r in catalog.root_states() if r["root_id"] == roots[1].root_id)
        cfg.config_path.write_text(
            tomli_w.dumps(
                {
                    "discovery_roots_mode": "replace",
                    "sources": [
                        {
                            "provider": "claude",
                            "path": str(root.path),
                            "namespace": name,
                            "enabled": name == "a",
                        }
                        for root, name in zip(roots, ("a", "b"), strict=True)
                    ],
                }
            )
        )
        updated = Config.load(cfg.config_path, cfg.data_dir)
        receipts = refresh(updated, catalog)
        assert len(receipts) == 1 and receipts[0]["root_id"] == roots[0].root_id
        assert (
            next(r for r in catalog.root_states() if r["root_id"] == roots[1].root_id) == previous
        )
        assert len(catalog.sessions()) == 2


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


@pytest.mark.parametrize("existing", [True, False])
def test_private_leaf_under_writable_parent_rejected_without_changes(tmp_path, existing):
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o700)
    leaf = parent / "private"
    if existing:
        leaf.mkdir(mode=0o700)
    parent.chmod(0o777)
    with pytest.raises(Failure, match="unsafe_data_dir"):
        ensure_private(leaf)
    assert leaf.exists() == existing
    assert parent.stat().st_mode & 0o777 == 0o777


def test_user_symlink_ancestor_rejected_before_creation(tmp_path):
    parent = tmp_path / "actual"
    parent.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(parent, target_is_directory=True)
    with pytest.raises(Failure, match="unsafe_data_dir"):
        ensure_private(alias / "private")
    assert not (parent / "private").exists()


def test_platform_alias_is_bound_to_canonical_private_directory(tmp_path):
    from pathlib import Path

    if not str(tmp_path).startswith("/private/var/"):
        pytest.skip("macOS root-owned /var alias")
    alias = Path(str(tmp_path).replace("/private/var/", "/var/", 1)) / "private"
    result = ensure_private(alias)
    assert result == alias.resolve()
    cfg = Config(alias, tmp_path / "config", [], "replace")
    cfg.prepare()
    assert cfg.data_dir == result


def test_creation_uses_open_parent_even_if_lexical_path_is_swapped(tmp_path, monkeypatch):
    import os

    parent, moved, outside = (tmp_path / name for name in ("parent", "moved", "outside"))
    parent.mkdir(mode=0o700)
    outside.mkdir(mode=0o700)
    original = os.mkdir

    def swapped(path, mode=0o777, *, dir_fd=None):
        if path == "private" and dir_fd is not None:
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
        return original(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", swapped)
    with pytest.raises(Failure, match="unsafe_data_dir"):
        ensure_private(parent / "private")
    assert not (outside / "private").exists()
    assert (moved / "private").is_dir()


def test_root_owned_sticky_parent_is_supported():
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="sessions-boundary-", dir="/tmp") as directory:
        private = ensure_private(Path(directory) / "private")
        assert private.stat().st_mode & 0o777 == 0o700


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


def test_filesystem_root_is_not_a_private_manager_directory():
    with pytest.raises(Failure, match="unsafe_data_dir"):
        ensure_private("/")
