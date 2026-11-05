"""All tests use explicit synthetic roots; never replace the user's HOME."""

import socket
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-warp", action="store_true", default=False)
    parser.addoption("--corpus", type=Path, default=None)
    parser.addoption("--codex-archive-executable", type=Path, default=None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def isolated(tmp_path):
    data = tmp_path / "manager"
    config = tmp_path / "fixture.toml"
    config.write_text('discovery_roots_mode = "replace"\n')
    return config, data


@pytest.fixture
def fake_executable(tmp_path):
    import sys

    path = tmp_path / "fake-cli"
    helper = Path(__file__).parent / "support" / "fake_cli.py"
    path.write_text(
        f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(helper)!r}, run_name='__main__')\n"
    )
    path.chmod(0o700)
    return path
