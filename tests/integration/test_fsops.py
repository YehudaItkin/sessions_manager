import os

import pytest

from sessions_manager.fsops import inventory, move_noreplace, verified_copy
from sessions_manager.models import Failure


def test_copy_hashes_and_atomic_no_overwrite(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one").write_text("selected")
    before = inventory(source, tmp_path)
    target = tmp_path / "backup"
    verified_copy(source, target, before)
    assert (target / "one").read_text() == "selected"
    assert (target / "one").stat().st_mode & 0o777 == 0o600
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    with pytest.raises(Failure, match="destination_conflict"):
        move_noreplace(source, occupied)
    assert source.exists() and occupied.exists()
    moved = tmp_path / "moved"
    move_noreplace(source, moved)
    assert not source.exists() and (moved / "one").read_text() == "selected"


def test_symlink_hardlink_and_escape_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    original = root / "original"
    original.write_text("safe")
    link = root / "link"
    link.symlink_to(original)
    with pytest.raises(Failure):
        inventory(root, tmp_path)
    link.unlink()
    os.link(original, link)
    with pytest.raises(Failure):
        inventory(root, tmp_path)
    with pytest.raises(Failure):
        inventory(tmp_path / "outside", root)


@pytest.mark.parametrize("name", ["../neighbor", "nested/../../neighbor"])
def test_dot_dot_never_escapes_native_boundary(tmp_path, name):
    from sessions_manager.fsops import secure_path

    root = tmp_path / "source"
    root.mkdir(mode=0o700)
    (root / "nested").mkdir(mode=0o700)
    neighbor = tmp_path / "neighbor"
    neighbor.write_text("synthetic neighboring history")
    with pytest.raises(Failure, match="path_outside_source_root"):
        secure_path(root / name, root)
    assert neighbor.read_text() == "synthetic neighboring history"
