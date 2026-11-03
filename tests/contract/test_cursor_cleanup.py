import sqlite3

import pytest

from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


def test_whole_per_chat_directory_neighbors_unchanged(tmp_path):
    with case(tmp_path, "cursor") as (service, root, uid, path, neighbor):
        before = tree_bytes(neighbor)
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "trashed"
        assert not path.exists() and tree_bytes(neighbor) == before


def test_live_handle_cannot_be_overridden(tmp_path):
    with case(tmp_path, "cursor") as (service, root, uid, path, neighbor):
        db = sqlite3.connect(path / "store.db")
        db.execute("SELECT * FROM meta").fetchone()
        try:
            with pytest.raises(Failure, match="observed_open_handle"):
                service.preview("trash", [uid])
        finally:
            db.close()


@pytest.mark.parametrize("provider,version", [("cursor", "2026.10.22-27dcf5f"), ("grok", "1.0.70")])
def test_detected_profile_roundtrip_survives_new_service(tmp_path, provider, version):
    from sessions_manager.catalog import Catalog
    from sessions_manager.cleanup import CleanupService
    from sessions_manager.config import Config
    from sessions_manager.discovery import refresh
    from sessions_manager.models import SourceRoot
    from tests.support import cursor_factory, grok_factory
    from tests.support.cleanup_case import version_cli

    factory = cursor_factory if provider == "cursor" else grok_factory
    path = factory.make(tmp_path / "native", "selected")
    neighbor = factory.make(tmp_path / "native", "neighbor")
    original, nearby = tree_bytes(path), tree_bytes(neighbor)
    root = SourceRoot.create(
        provider, tmp_path / "native", executable_path=version_cli(tmp_path, version, provider)
    )
    cfg = Config(tmp_path / "manager", tmp_path / "config.toml", [root], "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        service = CleanupService(cfg, catalog)
        uid = next(s.display_id for s in catalog.sessions() if s.native_id == "selected")
        assert catalog.get(uid).capabilities["cleanup"].state == "supported"
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        assert not path.exists()
    root.executable_version = None
    with Catalog(cfg.data_dir) as catalog:
        service = CleanupService(cfg, catalog)
        plan = service.preview("restore", [trash])
        result = service.commit("restore", [trash], plan["confirmation_token"])
        assert result["items"][0]["state"] == "restored"
    assert tree_bytes(path) == original and tree_bytes(neighbor) == nearby
