import json
import subprocess
import sys
import time

import pytest


def test_warm_new_process_search_budget(request):
    corpus = request.config.getoption("--corpus")
    if not corpus:
        pytest.skip("requires explicit synthetic --corpus")
    start = time.perf_counter()
    args = [
        sys.executable,
        "-m",
        "sessions_manager",
        "--config",
        str(corpus / "fixture.toml"),
        "--data-dir",
        (corpus / "benchmark-data.txt").read_text(),
        "--format",
        "json",
    ]
    result = subprocess.run(
        [*args, "list", "--query", "needle-09999"], capture_output=True, text=True, check=True
    )
    payload = json.loads(result.stdout)
    assert payload["data"]["total"] == 1
    assert payload["completeness"]["search"] == "complete"
    row = payload["data"]["items"][0]
    show = subprocess.run(
        [*args, "show", row["display_id"], "--limit", "1"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(show.stdout)["data"]["events"]
    short = subprocess.run(
        [*args, "list", "--query", "%_"], capture_output=True, text=True, check=True
    )
    assert json.loads(short.stdout)["completeness"]["search"] == "complete"
    elapsed = time.perf_counter() - start
    print(f"warm_search_navigation_seconds={elapsed:.3f}")
    assert elapsed <= 2


def test_warm_tui_first_meaningful_frame_in_new_process(request):
    import fcntl
    import os
    import pty
    import select
    import struct
    import termios

    corpus = request.config.getoption("--corpus")
    if not corpus:
        pytest.skip("requires explicit synthetic --corpus")
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 120, 0, 0))
    args = [
        sys.executable,
        "-m",
        "sessions_manager",
        "--config",
        str(corpus / "fixture.toml"),
        "--data-dir",
        (corpus / "benchmark-data.txt").read_text(),
    ]
    start = time.perf_counter()
    process = subprocess.Popen(
        args,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "TERM": "xterm-256color"},
        close_fds=True,
    )
    os.close(slave)
    seen = b""
    ready = None
    try:
        deadline = start + 5
        while time.perf_counter() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    seen += os.read(master, 65536)
                except OSError:
                    break
                if b"synthetic" in seen:
                    ready = time.perf_counter() - start
                    break
            if process.poll() is not None:
                break
        os.write(master, b"q")
        shutdown = time.perf_counter() + 10
        while process.poll() is None and time.perf_counter() < shutdown:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    os.read(master, 65536)
                except OSError:
                    break
        process.wait(timeout=2)
        assert ready is not None, "No synthetic session appeared in the TUI"
        print(f"warm_tui_first_frame_seconds={ready:.3f}")
        assert ready <= 2
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)


def test_warm_combined_filters_and_sort_before_pagination(request):
    corpus = request.config.getoption("--corpus")
    if not corpus:
        pytest.skip("requires explicit synthetic --corpus")
    start = time.perf_counter()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sessions_manager",
            "--config",
            str(corpus / "fixture.toml"),
            "--data-dir",
            (corpus / "benchmark-data.txt").read_text(),
            "--format",
            "json",
            "list",
            "--source",
            "claude",
            "--source",
            "grok",
            "--project",
            "projects",
            "--model",
            "synthetic",
            "--activity",
            "unknown",
            "--since",
            "2026-01-01T00:00:00Z",
            "--until",
            "2026-01-01T00:00:01Z",
            "--sort",
            "id",
            "--order",
            "desc",
            "--limit",
            "100",
            "--offset",
            "40",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    elapsed = time.perf_counter() - start
    assert payload["data"]["total"] == 5000
    ids = [s["native_id"] for s in payload["data"]["items"]]
    assert len(ids) == 100 and ids == sorted(ids, key=str.casefold, reverse=True)
    print(f"warm_combined_filter_sort_seconds={elapsed:.3f}")
    assert elapsed <= 2


@pytest.mark.asyncio
async def test_warm_tui_header_sort_budget(request):
    from sessions_manager.catalog import Catalog
    from sessions_manager.config import Config
    from sessions_manager.ui.app import SessionsApp

    corpus = request.config.getoption("--corpus")
    if not corpus:
        pytest.skip("requires explicit synthetic --corpus")
    cfg = Config.load(corpus / "fixture.toml", (corpus / "benchmark-data.txt").read_text())
    with Catalog(cfg.data_dir) as catalog:
        app = SessionsApp(cfg, catalog)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            previous = app.selected_uid()
            start = time.perf_counter()
            await pilot.click("#sessions", offset=(17, 0))
            await pilot.pause()
            elapsed = time.perf_counter() - start
            assert app.filters["sort"] == "id" and app.selected_uid() == previous
            assert app.query_one("#sessions").row_count == 10000
            print(f"warm_tui_sort_seconds={elapsed:.3f}")
            assert elapsed <= 2
