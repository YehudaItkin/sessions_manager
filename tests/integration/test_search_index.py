import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from tests.support.claude_factory import make


@pytest.mark.parametrize("query", ["STRASSE", "ж", "%_", 'literal "quote"', "x" * 40 + "needle"])
def test_literal_search_whole_messages(isolated, tmp_path, query):
    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path, text='Straße Ж literal %_ literal "quote" ' + "x" * 5000 + "needle")
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        assert len(catalog.matching_ids(query)) == 1
        assert catalog.matching_ids("no-such-text") == set()


def test_metadata_candidates_and_literal_nul_are_exact(isolated, tmp_path):
    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path, text="a\0b literal")
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        uid = catalog.sessions()[0].session_uid
        assert catalog.matching_ids("CLAUDE-ONE") == {uid}
        assert catalog.matching_ids("encoded-is-not-cwd") == set()
        assert catalog.matching_ids("\0") == {uid}
        assert catalog.matching_ids("not\0present") == set()
        catalog.connection.execute(
            "INSERT INTO search_fts(search_fts,rank) VALUES ('integrity-check',1)"
        )
