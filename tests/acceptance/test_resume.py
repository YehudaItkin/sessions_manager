import json

import pytest

from sessions_manager.discovery import adapter
from sessions_manager.launch import build_request, launch_current
from sessions_manager.models import Failure, SourceRoot
from tests.support.claude_factory import make


def test_foreground_child_and_changed_source(tmp_path, monkeypatch):
    root_path = tmp_path / "native"
    path = make(root_path)
    receipt = tmp_path / "receipt.json"
    binary = tmp_path / "native-cli"
    import sys

    binary.write_text(
        f"#!{sys.executable}\nimport os,sys,json\nfrom pathlib import Path\nPath({str(receipt)!r}).write_text(json.dumps({{'argv':sys.argv[1:],'cwd':os.getcwd()}}))\n"
    )
    binary.chmod(0o700)
    root = SourceRoot.create("claude", root_path, resume_context="native", executable_path=binary)
    session = adapter(root).discover().sessions[0]
    request = build_request(root, session, tmp_path / "data")
    result = launch_current(request)
    assert result["state"] == "child_exited"
    assert result["child_exit_code"] == 0
    assert json.loads(receipt.read_text())["argv"] == ["--resume", "claude-one"]
    assert "conversation_loaded" not in result
    request = build_request(root, session, tmp_path / "data")
    path.write_text(path.read_text() + "\n")
    with pytest.raises(Failure, match="source_changed"):
        launch_current(request)


@pytest.mark.asyncio
async def test_tui_resume_returns_same_selection(isolated, tmp_path, monkeypatch):
    import sys
    from contextlib import contextmanager

    from sessions_manager.catalog import Catalog
    from sessions_manager.config import Config
    from sessions_manager.discovery import refresh
    from sessions_manager.ui.app import SessionsApp

    config, data = isolated
    native = tmp_path / "native"
    make(native)
    binary = tmp_path / "child"
    binary.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n")
    binary.chmod(0o700)
    root = SourceRoot.create("claude", native, resume_context="native", executable_path=binary)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    suspended = []

    @contextmanager
    def suspend():
        suspended.append(True)
        yield

    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        monkeypatch.setattr(app, "suspend", suspend)
        async with app.run_test() as pilot:
            uid = app.selected_uid()
            app.resume_selected("current", catalog.get(uid).cwd)
            await pilot.pause()
            assert suspended == [True]
            assert app.selected_uid() == uid


def test_json_resume_has_one_stdout_envelope(isolated, tmp_path):
    import subprocess
    import sys

    import tomli_w

    config, data = isolated
    root = tmp_path / "native"
    make(root)
    executable = tmp_path / "harmless-stdout"
    executable.write_text(f'#!{sys.executable}\nprint("synthetic native terminal output")\n')
    executable.chmod(0o700)
    config.write_text(
        tomli_w.dumps(
            {
                "discovery_roots_mode": "replace",
                "sources": [
                    {
                        "provider": "claude",
                        "path": str(root),
                        "executable": str(executable),
                        "resume_context": "native",
                    }
                ],
            }
        )
    )
    args = [
        sys.executable,
        "-m",
        "sessions_manager",
        "--config",
        str(config),
        "--data-dir",
        str(data),
        "--format",
        "json",
    ]
    listed = subprocess.run([*args, "list"], capture_output=True, text=True, check=True)
    uid = json.loads(listed.stdout)["data"]["items"][0]["display_id"]
    result = subprocess.run([*args, "resume", uid], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["kind"] == "launch_result"
    assert "synthetic native terminal output" in result.stderr


def test_changed_executable_is_rejected_before_child(tmp_path):
    import sys

    make(tmp_path / "native")
    binary = tmp_path / "child"
    binary.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n")
    binary.chmod(0o700)
    root = SourceRoot.create(
        "claude", tmp_path / "native", resume_context="native", executable_path=binary
    )
    request = build_request(root, adapter(root).discover().sessions[0], tmp_path / "manager")
    binary.write_text(binary.read_text() + "# changed binary\n")
    with pytest.raises(Failure, match="executable_changed"):
        launch_current(request)


def test_shared_harmless_fixture_child_works_from_project_cwd(
    tmp_path, fake_executable, monkeypatch
):
    root = SourceRoot.create(
        "claude", tmp_path / "native", resume_context="native", executable_path=fake_executable
    )
    make(root.path)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("SESSIONS_TEST_RECEIPT", str(receipt))
    request = build_request(root, adapter(root).discover().sessions[0], tmp_path / "manager")
    result = launch_current(request)
    assert result["child_exit_code"] == 0
    assert json.loads(receipt.read_text())["cwd"] == request.cwd
