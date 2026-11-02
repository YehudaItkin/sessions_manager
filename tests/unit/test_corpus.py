import json
import tomllib

from tests.support.make_corpus import generate


def test_balanced_isolated_corpus(tmp_path):
    out = tmp_path / "corpus"
    generate(out, sessions=8, history_bytes=1000)
    config = tomllib.loads((out / "fixture.toml").read_text())
    assert config["discovery_roots_mode"] == "replace"
    assert len(config["sources"]) == 4
    expected = json.loads((out / "expected.json").read_text())
    assert len(expected["session_ids"]) == 8
    assert all(str(out) in s["path"] for s in config["sources"])
    assert expected["native_bytes"] > 0
    from sessions_manager.catalog import Catalog
    from sessions_manager.config import Config
    from sessions_manager.discovery import refresh
    from sessions_manager.statistics import summarize

    cfg = Config.load(out / "fixture.toml", tmp_path / "manager")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        metrics = summarize(catalog, catalog.sessions())["metrics"]
        assert metrics["messages"]["value"] == expected["metrics"]["messages"] == 14
        assert metrics["total_tokens"]["value"] == expected["metrics"]["known_total_tokens"] == 40
