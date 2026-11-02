import json

from sessions_manager.models import SourceRoot, public
from sessions_manager.sources.cursor import Adapter
from tests.support.cursor_factory import make


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
