import json

import pytest
import tomli_w
from typer.testing import CliRunner

from sessions_manager.catalog import Catalog
from sessions_manager.cli import app
from sessions_manager.models import HistoryResult, Session, SourceRoot


@pytest.mark.parametrize("query", [None, "needle"])
@pytest.mark.parametrize("only_complete", [False, True])
def test_cached_list_decodes_page_and_keeps_candidate_completeness(
    isolated, tmp_path, monkeypatch, query, only_complete
):
    import sessions_manager.catalog as module

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    root.path.mkdir()
    config.write_text(
        tomli_w.dumps(
            {
                "discovery_roots_mode": "replace",
                "sources": [{"provider": "claude", "path": str(root.path)}],
            }
        )
    )
    rows = [
        Session.build(
            root,
            f"row-{i:03}",
            root.path / str(i),
            title=f"needle-{i:03}" if i < 60 else "unmatched",
            model="complete" if i < 60 else "other",
            history_state="complete" if i < 60 else "partial",
            search_state="complete" if i < 60 else "partial",
            usage_state="complete" if i < 60 else "partial",
        )
        for i in range(61)
    ]
    with Catalog(data) as catalog:
        catalog.publish(
            root,
            rows,
            complete=True,
            histories={s.session_uid: HistoryResult([], s.history_state) for s in rows},
        )
    decode = module.session_payload
    decoded = []

    def observed(payload):
        session = decode(payload)
        decoded.append(session.session_uid)
        return session

    monkeypatch.setattr(module, "session_payload", observed)
    args = [
        "--config",
        str(config),
        "--data-dir",
        str(data),
        "--format",
        "json",
        "list",
        "--sort",
        "id",
        "--limit",
        "3",
        "--offset",
        "1",
    ]
    if query:
        args += ["--query", query]
    if only_complete:
        args += ["--model", "complete"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == (3 if query and not only_complete else 0), result.output
    payload = json.loads(result.stdout)
    assert payload["data"]["total"] == (60 if query or only_complete else 61)
    assert [s["native_id"] for s in payload["data"]["items"]] == ["row-001", "row-002", "row-003"]
    assert payload["completeness"]["search"] == ("complete" if only_complete else "partial")
    # Context may decode the displayed metadata once more; unloaded records are
    # never restored as typed Session objects for counting or completeness.
    assert len(decoded) <= 6
    assert set(decoded) == {rows[i].session_uid for i in (1, 2, 3)}
