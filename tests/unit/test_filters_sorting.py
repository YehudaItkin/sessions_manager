from dataclasses import replace

import pytest

from sessions_manager.models import Failure, Session, SourceRoot
from sessions_manager.search import QuerySpec


def row(tmp_path, native, **values):
    provider = values.pop("provider", "claude")
    return Session.build(
        SourceRoot.create(provider, tmp_path / provider), native, tmp_path / native, **values
    )


def test_filters_intersect_sources_project_model_activity_dates_and_scope(tmp_path):
    rows = [
        row(
            tmp_path,
            "match",
            provider="codex",
            cwd="/work/My Project",
            model="GPT-SYNTHETIC",
            activity="active",
            last_activity_at=1767225601000,
        ),
        row(
            tmp_path,
            "other-source",
            provider="grok",
            cwd="/work/My Project",
            model="GPT-SYNTHETIC",
            activity="active",
            last_activity_at=1767225601000,
        ),
    ]
    match = rows[0]
    rows += [
        replace(match, native_id="wrong-model", session_uid="wrong-model", model="other"),
        replace(
            match, native_id="wrong-activity", session_uid="wrong-activity", activity="unknown"
        ),
        replace(match, native_id="wrong-project", session_uid="wrong-project", cwd="/elsewhere"),
        replace(match, native_id="hidden", session_uid="hidden", hidden=True),
        replace(match, native_id="old", session_uid="old", last_activity_at=0),
    ]
    spec = QuerySpec(
        providers=["codex", "claude"],
        project="my project",
        model="gpt",
        activity="active",
        since="2026-01-01T00:00:00Z",
        until="2026-01-01T00:00:01Z",
    )
    assert [s.native_id for s in spec.filter(rows)] == ["match"]
    assert QuerySpec(activity="unknown").filter(rows) == [rows[3]]


@pytest.mark.parametrize(
    "field,values",
    [
        ("updated", {"last_activity_at": (10, 20, None)}),
        ("created", {"created_at": (10, 20, None)}),
        ("title", {"title": ("Alpha", "beta", None)}),
        ("project", {"cwd": ("/Alpha", "/beta", None)}),
        ("model", {"model": ("Alpha", "beta", None)}),
        ("size", {"known_bytes": (0, 200, None)}),
        ("activity", {"activity": ("active", "inactive", "unknown")}),
        ("id", {"native_id": ("Alpha", "beta", None)}),
    ],
)
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_sort_direction_unknowns_and_casefold(tmp_path, field, values, order):
    base = row(tmp_path, "base")
    key, names = next(iter(values.items()))
    rows = [replace(base, session_uid=f"uid-{i}", **{key: value}) for i, value in enumerate(names)]
    result = QuerySpec(sort=field, order=order).filter(list(reversed(rows)))
    assert [s.session_uid for s in result] == (
        ["uid-0", "uid-1", "uid-2"] if order == "asc" else ["uid-1", "uid-0", "uid-2"]
    )


def test_provider_manager_id_and_alias_sorting_is_stable(tmp_path):
    a = row(tmp_path, "A", provider="claude", last_activity_at=20, title="same")
    b = row(tmp_path, "B", provider="codex", last_activity_at=10, title="Same")
    assert QuerySpec(sort="source", order="desc").filter([a, b]) == [b, a]
    assert QuerySpec(sort="manager-id", order="asc").filter([b, a]) == sorted(
        [a, b], key=lambda s: s.display_id.casefold()
    )
    for order in ("asc", "desc"):
        assert QuerySpec(sort="title", order=order).filter([b, a]) == sorted(
            [a, b], key=lambda s: s.session_uid
        )
    assert QuerySpec(sort="recent").filter([b, a]) == [a, b]
    assert QuerySpec(sort="oldest").filter([b, a]) == [b, a]
    assert (
        QuerySpec(sort="created")
        .filter([replace(a, created_at=20), replace(b, created_at=10)])[0]
        .native_id
        == "A"
    )


@pytest.mark.parametrize(
    "options", [{"sort": "bad"}, {"order": "sideways"}, {"activity": "running"}]
)
def test_invalid_selection_is_rejected_before_data_is_needed(options):
    with pytest.raises(Failure, match="invalid_query"):
        QuerySpec(**options).filter([])
