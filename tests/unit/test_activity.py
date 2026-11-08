from sessions_manager.activity import verify


def test_positive_evidence_requires_pid_birth_executable_and_cwd():
    record = {"pid": 123, "pid_start": "birth", "executable": "/fake/grok", "cwd": "/project"}
    process = {"pid_start": "birth", "executable": "/fake/grok", "cwd": "/project"}
    assert verify(record, lambda pid: process) == "active"
    assert verify(record, lambda pid: {**process, "pid_start": "reused"}) == "unknown"
    assert verify(record, lambda pid: {**process, "executable": "/wrong"}) == "unknown"
    assert verify(record, lambda pid: None) == "unknown"
    assert verify({}, lambda pid: process) == "unknown"


def test_grok_registry_binds_session_cwd_process_birth_and_executable(tmp_path):
    import json

    from sessions_manager.activity import observe
    from sessions_manager.models import Session, SourceRoot

    root = SourceRoot.create("grok", tmp_path, executable_path=tmp_path / "grok")
    session = Session.build(root, "one", tmp_path / "session", cwd=str(tmp_path / "project"))
    record = {
        "session_id": "one",
        "pid": 123,
        "pid_start": 1700000000,
        "cwd": session.cwd,
        "opened_at": "2026-01-01T00:00:00Z",
    }
    (tmp_path / "active_sessions.json").write_text(json.dumps([record]))

    def probe(pid):
        return {"pid_start": 1700000000, "executable": str(root.executable_path)}

    observe(root, [session], probe=probe)
    assert session.activity == "active"
    observe(
        root,
        [session],
        probe=lambda pid: {"pid_start": 1800000000, "executable": str(root.executable_path)},
    )
    assert session.activity == "unknown"
    assert session.activity_evidence["status"] == "unknown"


def test_registry_evidence_reaches_all_matching_locations_and_survives_stale_record(tmp_path):
    import json

    from sessions_manager.activity import observe
    from sessions_manager.models import Session, SourceRoot

    root = SourceRoot.create("grok", tmp_path, executable_path=tmp_path / "grok")
    sessions = [
        Session.build(root, "same", tmp_path / name, cwd=str(tmp_path / "project"))
        for name in ("a", "b")
    ]
    unrelated = Session.build(root, "same", tmp_path / "other", cwd=str(tmp_path / "different"))
    record = {"session_id": "same", "pid": 123, "pid_start": 100, "cwd": sessions[0].cwd}
    (tmp_path / "active_sessions.json").write_text(
        json.dumps([record, {**record, "pid_start": 99}])
    )
    observe(
        root,
        [*sessions, unrelated],
        probe=lambda pid: {"pid_start": 100, "executable": str(root.executable_path)},
    )
    assert [s.activity for s in sessions] == ["active", "active"]
    assert all(s.activity_evidence["status"] == "active" for s in sessions)
    assert unrelated.activity == "unknown" and not unrelated.activity_evidence
    (tmp_path / "active_sessions.json").write_text("invalid")
    observe(root, [*sessions, unrelated])
    assert all(s.activity == "unknown" for s in [*sessions, unrelated])
