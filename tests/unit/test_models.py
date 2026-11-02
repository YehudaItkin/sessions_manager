import pytest

from sessions_manager.models import Capability, Session, SourceRoot, counter, safe_text, timestamp


def test_counter_unknown_zero_and_bool():
    assert counter(None) is None
    assert counter(0) == 0
    for value in (True, -1, 1.5, "1"):
        with pytest.raises(ValueError):
            counter(value)


def test_identity_namespace_and_root_move(tmp_path):
    a = SourceRoot.create("codex", tmp_path / "a")
    b = SourceRoot.create("codex", tmp_path / "b")
    first = Session.build(a, "native", tmp_path / "a" / "x")
    moved = Session.build(b, "native", tmp_path / "b" / "x")
    other = Session.build(SourceRoot.create("claude", tmp_path / "c"), "native", tmp_path / "c")
    assert first.session_uid == moved.session_uid
    assert first.session_uid != other.session_uid
    assert first.native_id == "native"


def test_surrogate_has_no_unsafe_capability(tmp_path):
    root = SourceRoot.create("codex", tmp_path)
    session = Session.build(root, None, tmp_path / "artifact")
    assert session.capabilities["resume"].state == "unavailable"
    assert session.capabilities["cleanup"].state == "unavailable"


def test_timestamp_and_output_sanitization():
    assert timestamp("2026-01-01T00:00:00Z") == 1767225600000
    assert timestamp("garbage") is None
    assert "\x1b" not in safe_text("\x1b[31mhello\x1b]0;bad\x07\u202eevil")
    assert "\u202e" not in safe_text("\u202e")
    assert Capability("unavailable", "unknown_format").reason == "unknown_format"


def test_short_manager_handles_grow_on_collision(tmp_path):
    from sessions_manager.models import short_handles

    root = SourceRoot.create("claude", tmp_path)
    first = Session.build(root, "first", tmp_path / "first")
    second = Session.build(root, "second", tmp_path / "second")
    first.display_id = "s-12345678aaaa"
    second.display_id = "s-12345678bbbb"
    handles = short_handles([first, second])
    assert handles[first.session_uid] != handles[second.session_uid]
    assert len(handles[first.session_uid]) > 10


def test_session_rejects_untyped_metadata_and_bool_time(tmp_path):
    root = SourceRoot.create("claude", tmp_path)
    with pytest.raises(ValueError):
        Session.build(root, "one", tmp_path / "one", model={"credential": "must not persist"})
    with pytest.raises(ValueError):
        Session.build(root, "one", tmp_path / "one", created_at=True)


def test_surrogate_follows_same_filesystem_artifact_after_move(tmp_path):
    from sessions_manager.sources.base import fingerprint

    path = tmp_path / "one"
    path.write_text("synthetic")
    root = SourceRoot.create("claude", tmp_path)
    before = Session.build(root, None, path, fingerprint=fingerprint(path))
    path.rename(tmp_path / "moved")
    after = Session.build(
        root, None, tmp_path / "moved", fingerprint=fingerprint(tmp_path / "moved")
    )
    assert before.session_uid == after.session_uid
    assert after.capabilities["resume"].state == "unavailable"
