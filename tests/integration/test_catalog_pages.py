from dataclasses import replace

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.models import Failure, Session, SourceRoot
from sessions_manager.search import SORT_OPTIONS, QuerySpec


@pytest.fixture
def paged(tmp_path):
    root = SourceRoot.create("claude", tmp_path / "native")
    rows = [
        Session.build(
            root,
            f"row-{i:03}",
            root.path / str(i),
            title=["Straße", "STRASSE", "", None][i % 4],
            preview="needle %_" if i % 3 else None,
            cwd="/My Project" if i % 2 else None,
            model="SYNTH" if i % 2 else None,
            activity=["active", "inactive", "unknown"][i % 3],
            known_bytes=i if i % 2 else None,
            created_at=i if i % 2 else None,
            last_activity_at=1767225600000 + i if i % 2 else None,
        )
        for i in range(225)
    ]
    rows[1] = replace(
        rows[1], extra={"date_provenance": {"last_activity_at": {"confidence": "ambiguous"}}}
    )
    with Catalog(tmp_path / "data") as catalog:
        catalog.publish(root, rows, complete=True)
        catalog.hide([rows[2].session_uid], True)
        yield catalog, root, rows


@pytest.mark.parametrize("sort", [key for _, key in SORT_OPTIONS] + ["recent", "oldest"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_pages_match_existing_query_semantics(paged, sort, order):
    catalog, _, _ = paged
    spec = QuerySpec(sort=sort, order=order)
    expected = [s.session_uid for s in spec.filter(catalog.sessions(), catalog)]
    found = []
    revision = None
    for offset in range(0, len(expected) + 100, 100):
        page = catalog.query_page(spec, 100, offset)
        assert page.total == len(expected)
        assert revision is None or page.revision == revision
        revision = page.revision
        found.extend(s.session_uid for s in page.rows)
    assert found == expected
    assert len(set(found)) == len(found)


@pytest.mark.parametrize(
    "options",
    [
        {"project": "MY PROJECT", "model": "synth", "activity": "inactive"},
        {"since": "2026-01-01T00:00:00Z", "until": "2026-01-01T00:00:01Z"},
        {"scope": "hidden"},
        {"scope": "all"},
        {"providers": ["grok"]},
        {"query": "strasse"},
        {"query": "%_"},
        {"query": "e"},
    ],
)
def test_page_filters_and_selection_match_existing_query(paged, options):
    catalog, _, rows = paged
    spec = QuerySpec(**options)
    expected = [s.session_uid for s in spec.filter(catalog.sessions(), catalog)]
    assert [s.session_uid for s in catalog.query_page(spec, 300, 0).rows] == expected
    selected = {s.session_uid for s in rows[90:210]}
    assert catalog.matching_selection(spec, selected) == selected.intersection(expected)
    if expected:
        assert catalog.query_position(spec, expected[-1]) == len(expected) - 1
    assert catalog.query_position(spec, "absent") is None


def test_page_decodes_only_requested_rows_and_revision_tracks_writers(paged, monkeypatch):
    import sessions_manager.catalog as module

    catalog, _, rows = paged
    decode = module.session_payload
    calls = []
    monkeypatch.setattr(
        module, "session_payload", lambda body: (calls.append(body), decode(body))[1]
    )
    page = catalog.query_page(QuerySpec(), 7, 100)
    assert len(calls) == 7
    catalog.hide([rows[0].session_uid], True)
    assert catalog.query_page(QuerySpec(), 7, 100).revision != page.revision
    with Catalog(catalog.data_dir) as other:
        before = catalog.query_page(QuerySpec(), 1, 0)
        other.hide([rows[1].session_uid], True)
        assert catalog.query_page(QuerySpec(), 1, 0).revision != before.revision
    assert catalog.connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_page_rejects_invalid_queries_and_bounds(paged):
    catalog, _, _ = paged
    for spec, limit, offset in [
        (QuerySpec(sort="bad"), 100, 0),
        (QuerySpec(), -1, 0),
        (QuerySpec(), 100, -1),
    ]:
        with pytest.raises(Failure):
            catalog.query_page(spec, limit, offset)
