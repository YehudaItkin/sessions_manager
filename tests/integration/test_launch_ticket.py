import os

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import ensure_private
from sessions_manager.discovery import adapter
from sessions_manager.launch import build_request
from sessions_manager.models import Failure, SourceRoot
from sessions_manager.warp import claim_ticket, create_ticket
from tests.support.claude_factory import make


def setup(tmp_path, fake_executable):
    root = SourceRoot.create(
        "claude", tmp_path / "native", resume_context="native", executable_path=fake_executable
    )
    make(root.path)
    request = build_request(
        root, adapter(root).discover().sessions[0], tmp_path / "data", target="warp"
    )
    ensure_private(tmp_path / "data")
    ensure_private(tmp_path / "data/launches")
    return request


def test_ticket_owner_mode_one_shot_and_tamper(tmp_path, fake_executable):
    request = setup(tmp_path, fake_executable)
    with Catalog(tmp_path / "data") as catalog:
        token = create_ticket(catalog, request)
        manifest = tmp_path / "data/launches" / (request.launch_id + ".json")
        assert manifest.stat().st_mode & 0o777 == 0o600
        value = claim_ticket(catalog, token)
        assert value.history_locator == request.history_locator
        with pytest.raises(Failure, match="launch_ticket_replayed"):
            claim_ticket(catalog, token)
        other = setup(tmp_path / "other", fake_executable)
        other.data_dir = str(catalog.data_dir)
        token = create_ticket(catalog, other)
        record = catalog.connection.execute(
            "SELECT launch_id FROM launches WHERE state='requested'"
        ).fetchone()
        manifest = tmp_path / "data/launches" / (record[0] + ".json")
        manifest.write_text("{}")
        with pytest.raises(Failure, match="launch_manifest_changed"):
            claim_ticket(catalog, token)


def test_expiry_rejected(tmp_path, fake_executable):
    request = setup(tmp_path, fake_executable)
    request.expires_at = 0
    with Catalog(tmp_path / "data") as catalog:
        token = create_ticket(catalog, request)
        with pytest.raises(Failure, match="launch_ticket_expired"):
            claim_ticket(catalog, token)


def test_concurrent_claim_has_exactly_one_winner(tmp_path, fake_executable, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sessions_manager.warp as warp

    request = setup(tmp_path, fake_executable)
    with Catalog(tmp_path / "data") as catalog:
        token = create_ticket(catalog, request)
    barrier = threading.Barrier(2)
    original = os.open

    def synchronized(path, *args, **kwargs):
        if str(path).endswith(".json"):
            barrier.wait(timeout=5)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(warp.os, "open", synchronized)

    def attempt(_):
        with Catalog(tmp_path / "data") as catalog:
            try:
                claim_ticket(catalog, token)
                return "claimed"
            except Failure as failure:
                return failure.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ["claimed", "launch_ticket_replayed"]


def test_expired_launch_housekeeping_preserves_trash(tmp_path, fake_executable):
    from sessions_manager.warp import cleanup_expired

    request = setup(tmp_path, fake_executable)
    request.expires_at = 0
    trash = tmp_path / "data/trash"
    trash.mkdir()
    (trash / "keep").write_text("recoverable session")
    with Catalog(tmp_path / "data") as catalog:
        create_ticket(catalog, request)
        cleanup_expired(catalog)
        assert not list((tmp_path / "data/launches").iterdir())
        assert (trash / "keep").read_text() == "recoverable session"
        assert catalog.connection.execute("SELECT state FROM launches").fetchone()[0] == "expired"
