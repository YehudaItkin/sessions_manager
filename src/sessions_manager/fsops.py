"""Owner-checked inventory, durable backups and atomic no-replace moves."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from .models import Failure


def secure_path(path, boundary):
    path, boundary = Path(path).absolute(), Path(boundary).absolute()
    try:
        relative = path.relative_to(boundary)
    except ValueError:
        raise Failure("path_outside_source_root", 5) from None
    current = boundary
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
            raise Failure("unsafe_artifact_owner_or_link", 5)
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise Failure("unsupported_artifact_type", 5)
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise Failure("ambiguous_hardlink", 5)
        if info.st_mode & 0o022:
            raise Failure("unsafe_writable_artifact", 5)
    return path


def _stat(info):
    return {
        "dev": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }


def inventory(path, boundary):
    path = secure_path(path, boundary)
    records = {}

    def visit(current, relative):
        secure_path(current, path.parent)
        info = current.lstat()
        record = {
            "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file",
            "mode": stat.S_IMODE(info.st_mode),
            "stat": _stat(info),
        }
        if record["kind"] == "file":
            descriptor = os.open(current, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if _stat(before) != record["stat"] or before.st_nlink != 1:
                    raise Failure("source_changed", 5)
                digest = hashlib.sha256()
                while data := stream.read(1024 * 1024):
                    digest.update(data)
                if _stat(os.fstat(stream.fileno())) != record["stat"]:
                    raise Failure("source_changed", 5)
            record["sha256"] = digest.hexdigest()
            record["size"] = info.st_size
        records[relative] = record
        if len(records) > 100000:
            raise Failure("bundle_inventory_limit", 4)
        if record["kind"] == "directory":
            with os.scandir(current) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
            for child in children:
                visit(
                    Path(child.path), child.name if relative == "." else relative + "/" + child.name
                )

    visit(path, ".")
    return records


def matches(path, expected, *, fingerprints=False, subset=False):
    if not Path(path).exists() or Path(path).is_symlink():
        return False
    actual = inventory(path, Path(path).parent)
    if (not subset and set(actual) != set(expected)) or not set(actual) <= set(expected):
        return False
    for name, row in actual.items():
        wanted = expected[name]
        if row["kind"] != wanted["kind"] or row.get("sha256") != wanted.get("sha256"):
            return False
        if fingerprints and row["stat"] != wanted["stat"]:
            return False
    return True


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check_space(destination, needed):
    if shutil.disk_usage(destination).free < needed + 1024 * 1024:
        raise Failure("insufficient_space", 6)


def verified_copy(source, destination, expected, *, fault=None):
    source, destination = Path(source), Path(destination)
    for name, record in sorted(expected.items(), key=lambda item: (item[0].count("/"), item[0])):
        src = source if name == "." else source / name
        dst = destination if name == "." else destination / name
        if record["kind"] == "directory":
            if not dst.exists():
                dst.mkdir(mode=0o700)
            elif dst.is_symlink() or not dst.is_dir():
                raise Failure("backup_conflict", 6)
            continue
        if dst.exists():
            single = {".": record}
            if not matches(dst, single):
                raise Failure("backup_conflict", 6)
        else:
            if fault:
                fault("before_copy")
            srcfd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
            dstfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(srcfd, "rb") as reader, os.fdopen(dstfd, "wb") as writer:
                if _stat(os.fstat(reader.fileno())) != record["stat"]:
                    raise Failure("source_changed", 5)
                shutil.copyfileobj(reader, writer, 1024 * 1024)
                if fault:
                    fault("after_copy")
                writer.flush()
                os.fsync(writer.fileno())
                if fault:
                    fault("after_fsync")
            if not matches(dst, {".": record}):
                raise Failure("backup_hash_mismatch", 6)
            if fault:
                fault("after_hash")
        if fault:
            fault("backup_file")
    if not matches(destination, expected):
        raise Failure("backup_hash_mismatch", 6)
    directories = [
        destination / name
        for name, row in expected.items()
        if row["kind"] == "directory" and name != "."
    ]
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        fsync_dir(directory)
    if destination.is_dir():
        fsync_dir(destination)
    fsync_dir(destination.parent)


def same_device(source, destination):
    return Path(source).stat().st_dev == Path(destination).stat().st_dev


def move_noreplace(source, destination):
    source, destination = Path(source), Path(destination)
    if not same_device(source.parent, destination.parent):
        raise Failure("cross_device_unavailable", 4)
    if sys.platform != "darwin":
        raise Failure("no_replace_unavailable", 4)
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.renameatx_np
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    srcfd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    dstfd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        result = function(
            srcfd, os.fsencode(source.name), dstfd, os.fsencode(destination.name), 0x4
        )
        if result:
            code = ctypes.get_errno()
            if code in (errno.EEXIST, errno.ENOTEMPTY):
                raise Failure("destination_conflict", 5)
            if code in (errno.EXDEV, errno.ENOTSUP, errno.EINVAL):
                raise Failure("no_replace_unavailable", 4)
            raise OSError(code, "atomic_move_failed")
        os.fsync(srcfd)
        os.fsync(dstfd)
    finally:
        os.close(srcfd)
        os.close(dstfd)


def open_handles(paths):
    executable = Path("/usr/sbin/lsof")
    if not executable.is_file():
        raise Failure("handle_probe_unavailable", 4)
    files = [str(path) for path in paths]
    for offset in range(0, len(files), 128):
        try:
            result = subprocess.run(
                [str(executable), "-n", "-F", "p", "--", *files[offset : offset + 128]],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise Failure("handle_probe_unavailable", 4) from None
        if any(line.startswith("p") for line in result.stdout.splitlines()):
            return True
        if result.returncode not in (0, 1):
            raise Failure("handle_probe_unavailable", 4)
    return False


def apply_modes(path, expected, *, private=False):
    for name, row in sorted(expected.items(), key=lambda item: item[0].count("/"), reverse=True):
        target = Path(path) if name == "." else Path(path) / name
        mode = (0o700 if row["kind"] == "directory" else 0o600) if private else row["mode"] & 0o777
        os.chmod(target, mode, follow_symlinks=False)


def remove_owned_tree(path):
    path = Path(path)
    inventory(path, path.parent)
    shutil.rmtree(path)
    fsync_dir(path.parent)
