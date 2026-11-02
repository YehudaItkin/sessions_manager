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
