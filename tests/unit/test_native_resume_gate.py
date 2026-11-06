import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    sys.platform != "darwin", reason="native gate containment requires macOS sandbox-exec"
)
def test_native_gate_denies_network_and_outside_files(tmp_path):
    from tests.support.native_resume_gate import native_environment, sandbox_command

    scratch = tmp_path / "fixture"
    scratch.mkdir(mode=0o700)
    (scratch / "home").mkdir()
    outside = tmp_path / "private-sentinel"
    outside.write_text("SYNTHETIC-PRIVATE")
    binary = Path("/opt/homebrew/bin/python3.12")
    code = """import os,json,socket
from pathlib import Path
out={"home":os.environ["HOME"],"api_key_present":bool(os.environ.get("ANTHROPIC_API_KEY"))}
for kind,path in [("read",Path("../private-sentinel")),("write",Path("../outside-write"))]:
 try:
  path.read_text() if kind=="read" else path.write_text("unwanted")
  out[kind]="allowed"
 except PermissionError: out[kind]="denied"
sock=socket.socket()
out["network_errno"]=sock.connect_ex(("127.0.0.1",9))
Path("inside-write").write_text("synthetic")
print(json.dumps(out))"""
    env = native_environment(scratch)
    assert "ANTHROPIC_API_KEY" not in env
    result = subprocess.run(
        sandbox_command(scratch, binary, ["-B", "-c", code]),
        cwd=scratch,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["read"] == observed["write"] == "denied"
    assert observed["network_errno"] in (1, 13)
    assert observed["home"] == str(scratch / "home")
    assert (scratch / "inside-write").read_text() == "synthetic"
    assert outside.read_text() == "SYNTHETIC-PRIVATE" and not (tmp_path / "outside-write").exists()
    assert os.environ.get("HOME") != str(scratch / "home")


def test_native_gate_receipt_requires_marker_identity_cwd_and_no_new_session():
    from tests.support.native_resume_gate import receipt

    args = {"marker_visible": True, "same_id": True, "same_cwd": True, "no_new_sessions": True}
    assert receipt("claude", **args)["conversation_loaded"]
    for key in args:
        assert not receipt("claude", **(args | {key: False}))["conversation_loaded"]


@pytest.mark.parametrize(
    "provider,output",
    [
        ("claude", "2.1.2999 (Claude Code)\n"),
        ("grok", "grok 1.0.700 (synthetic) [stable]\n"),
        ("cursor", "2026.10.22-27dcf5f-unknown\n"),
    ],
)
def test_native_gate_rejects_version_prefix_before_any_resume(monkeypatch, provider, output):
    from types import SimpleNamespace

    from tests.support.native_resume_gate import verify

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=output)
    )
    monkeypatch.setattr(
        "tests.support.native_resume_gate.terminal_run",
        lambda *a, **k: pytest.fail("unverified profile launched"),
    )
    with pytest.raises(RuntimeError, match="native_gate_profile_unverified"):
        verify(provider, Path(sys.executable))


@pytest.mark.skipif(
    sys.platform != "darwin", reason="native gate containment requires macOS sandbox-exec"
)
def test_terminal_gate_cleans_owned_child_if_group_signal_is_denied(tmp_path, monkeypatch):
    from tests.support.native_resume_gate import native_environment, sandbox_command, terminal_run

    (tmp_path / "home").mkdir()
    code = 'import os,signal; from pathlib import Path; Path("child.pid").write_text(str(os.getpid())); print("SYNTHETIC-MARKER",flush=True); signal.pause()'
    command = sandbox_command(tmp_path, Path("/opt/homebrew/bin/python3.12"), ["-B", "-c", code])

    def denied(*args):
        raise PermissionError("synthetic group signal denial")

    monkeypatch.setattr(os, "killpg", denied)
    visible, _, _ = terminal_run(
        command, tmp_path, native_environment(tmp_path), "SYNTHETIC-MARKER", timeout=3
    )
    assert visible
    pid = int((tmp_path / "child.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.skipif(
    sys.platform != "darwin", reason="native gate containment requires macOS sandbox-exec"
)
def test_native_gate_also_denies_shared_system_temporary_data(tmp_path):
    import tempfile

    from tests.support.native_resume_gate import native_environment, sandbox_command

    (tmp_path / "home").mkdir()
    with tempfile.NamedTemporaryFile(
        dir="/private/tmp", prefix="sessions-native-private-"
    ) as sentinel:
        sentinel.write(b"SYNTHETIC-PRIVATE-TEMP")
        sentinel.flush()
        code = 'from pathlib import Path; import sys;\ntry: Path(sys.argv[1]).read_bytes()\nexcept PermissionError: print("denied")\nelse: print("allowed")'
        result = subprocess.run(
            sandbox_command(
                tmp_path, Path("/opt/homebrew/bin/python3.12"), ["-B", "-c", code, sentinel.name]
            ),
            cwd=tmp_path,
            env=native_environment(tmp_path),
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "denied"
