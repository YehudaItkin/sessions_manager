from sessions_manager.models import SourceRoot
from sessions_manager.watch import RefreshSchedule, observe_roots


def test_stat_observer_tracks_files_directories_and_unavailability_without_reading(
    tmp_path, monkeypatch
):
    from pathlib import Path

    root = SourceRoot.create("claude", tmp_path / "native")
    root.path.mkdir()
    file = root.path / "history"
    file.write_text("first")
    original = observe_roots([root])
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert observe_roots([root]) == original
    file.write_text("second version")
    changed = observe_roots([root])
    assert changed != original
    file.unlink()
    assert observe_roots([root]) != changed
    root.path.rmdir()
    assert observe_roots([root])[root.root_id] is None


def test_observer_does_not_follow_nested_links(tmp_path):
    root = SourceRoot.create("claude", tmp_path / "native")
    root.path.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    file = outside / "private"
    file.write_text("first")
    (root.path / "link").symlink_to(outside)
    before = observe_roots([root])
    file.write_text("changed outside")
    assert observe_roots([root]) == before


def test_schedule_uses_completion_time_and_independent_thirty_second_retry(tmp_path):
    now = [0.0]
    schedule = RefreshSchedule(clock=lambda: now[0])
    a = SourceRoot.create("claude", tmp_path / "a")
    alias = SourceRoot.create("claude", tmp_path / "alias")
    b = SourceRoot.create("grok", tmp_path / "b")
    roots = [a, alias, b]
    observations = {r.root_id: (1,) for r in roots}
    assert schedule.changed(roots, observations) == {"claude", "grok"}
    now[0] = 20  # A long scan never makes the next cycle overdue.
    schedule.finished({"claude": False, "grok": True})
    assert schedule.next_poll == 25
    assert schedule.changed(roots, observations) == set()
    observations[a.root_id] = (2,)
    observations[b.root_id] = (2,)
    now[0] = 25
    assert schedule.changed(roots, observations) == {"grok"}
    now[0] = 49
    assert schedule.changed(roots, observations) == set()
    now[0] = 50
    assert schedule.changed(roots, observations) == {"claude"}


def test_changes_during_scan_are_detected_next_cycle(tmp_path):
    schedule = RefreshSchedule(clock=lambda: 0)
    root = SourceRoot.create("claude", tmp_path / "a")
    assert schedule.changed([root], {root.root_id: (1,)}) == {"claude"}
    schedule.finished({"claude": True})
    assert schedule.changed([root], {root.root_id: (2,)}) == {"claude"}


def test_excluded_failed_provider_does_not_spin_on_expired_deadline():
    now = [0.0]
    schedule = RefreshSchedule(clock=lambda: now[0])
    schedule.finished({"claude": False})
    now[0] = 40
    # The current source filter only polls healthy providers.
    schedule.finished({})
    assert schedule.next_poll == 45
    assert schedule.retry_at["claude"] == 30


def test_observation_cancel_stops_between_entries_and_discards_snapshot(tmp_path, monkeypatch):
    import threading

    import sessions_manager.watch as module

    root = SourceRoot.create("claude", tmp_path / "native")
    root.path.mkdir()
    for name in ("one", "two", "three"):
        (root.path / name).write_text("synthetic")
    cancel = threading.Event()
    original = module.os.scandir
    visited = []

    class Entry:
        def __init__(self, entry):
            self.entry, self.name = entry, entry.name

        def stat(self, **kwargs):
            visited.append(self.name)
            cancel.set()
            return self.entry.stat(**kwargs)

    class Entries:
        def __init__(self, fd):
            self.entries = original(fd)

        def __enter__(self):
            return (Entry(entry) for entry in self.entries)

        def __exit__(self, *args):
            self.entries.close()

    monkeypatch.setattr(module.os, "scandir", Entries)
    assert observe_roots([root], cancel=cancel) is None
    assert len(visited) == 1
    visited.clear()
    assert observe_roots([root], cancel=cancel) is None
    assert visited == []


def test_cancelled_unavailable_root_does_not_become_a_source_error(tmp_path, monkeypatch):
    import threading

    import sessions_manager.watch as module

    root = SourceRoot.create("claude", tmp_path / "native")
    cancel = threading.Event()

    def unavailable(*args):
        cancel.set()
        raise OSError("synthetic missing root during shutdown")

    monkeypatch.setattr(module, "source_directory", unavailable)
    assert observe_roots([root], cancel=cancel) is None
