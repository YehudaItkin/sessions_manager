import sys
import time

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import ensure_private
from sessions_manager.discovery import adapter
from sessions_manager.launch import build_request
from sessions_manager.models import SourceRoot
from sessions_manager.warp import deliver
from tests.support.claude_factory import make


def test_opt_in_harmless_runtime(request, tmp_path):
    if not request.config.getoption("--run-warp"):
        pytest.skip("requires explicit --run-warp; opens harmless child only")
    cwd = tmp_path / "spaces кириллица quotes ' $ {{literal}}"
    cwd.mkdir()
    rootpath = tmp_path / "native"
    make(rootpath, cwd=cwd)
    ack = tmp_path / "ack"
    binary = tmp_path / "harmless"
    binary.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(ack)!r}).write_text('ok')\n"
    )
    binary.chmod(0o700)
    root = SourceRoot.create("claude", rootpath, resume_context="native", executable_path=binary)
    data = ensure_private(tmp_path / "manager")
    ensure_private(data / "launches")
    with Catalog(data) as catalog:
        result = deliver(
            catalog, build_request(root, adapter(root).discover().sessions[0], data, target="warp")
        )
        assert result["state"] == "delivered"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not ack.exists():
            time.sleep(0.1)
        assert ack.read_text() == "ok"
