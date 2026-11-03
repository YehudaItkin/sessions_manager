import json

from sessions_manager.models import SourceRoot, public
from sessions_manager.sources.cursor import Adapter
from tests.support.cursor_factory import make


def test_missing_sidecar_uses_native_metadata_and_verified_workspace_neighbor(tmp_path):
    cwd = tmp_path / "project"
    make(tmp_path, "first", cwd=cwd)
    missing = make(tmp_path, "second", cwd=cwd)
    (missing / "meta.json").unlink()
    result = Adapter(SourceRoot.create("cursor", tmp_path)).discover()
    assert result.complete
    assert {s.native_id for s in result.sessions} == {"first", "second"}
    recovered = next(s for s in result.sessions if s.native_id == "second")
    assert recovered.cwd == str(cwd)
    assert recovered.last_activity_at is None
    assert not (missing / "meta.json").exists()


def test_unproven_workspace_is_not_guessed_from_hash(tmp_path):

    chat = make(tmp_path, cwd=tmp_path / "project")
    (chat / "meta.json").unlink()
    result = Adapter(SourceRoot.create("cursor", tmp_path)).discover()
    assert len(result.sessions) == 1
    assert result.sessions[0].cwd is None


def test_whitelist_excludes_secret(tmp_path):
    make(tmp_path)
    result = Adapter(SourceRoot.create("cursor", tmp_path)).discover()
    assert result.complete
    session = result.sessions[0]
    assert session.native_id == "cursor-one"
    encoded = json.dumps(public(session))
    assert "blobEncryptionKey" not in encoded
    assert "SYNTHETIC-SECRET" not in encoded
    assert session.usage_state == "unavailable"
