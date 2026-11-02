import tempfile
import time
from pathlib import Path

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh


def test_cold_budget(request):
    corpus = request.config.getoption("--corpus")
    if not corpus:
        pytest.skip("requires explicit synthetic --corpus")
    cfg = Config.load(
        corpus / "fixture.toml", Path(tempfile.mkdtemp(prefix="sessions-final-cold-"))
    )
    cfg.prepare()
    start = time.perf_counter()
    with Catalog(cfg.data_dir) as catalog:
        result = refresh(cfg, catalog)
        assert all(r["state"] == "complete" for r in result)
        assert len(catalog.sessions()) == 10000
    elapsed = time.perf_counter() - start
    (corpus / "benchmark-data.txt").write_text(str(cfg.data_dir))
    print(f"cold_discovery_seconds={elapsed:.3f} data={cfg.data_dir}")
    assert elapsed <= 10
