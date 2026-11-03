"""Bounded version-only probe; never start a conversation or list native sessions."""

import os
import re
import subprocess
from functools import lru_cache


@lru_cache(maxsize=32)
def _claude_version(path, device, inode, size, modified):
    try:
        result = subprocess.run(
            [path, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+) \(Claude Code\)\s*", result.stdout)
        return match.group(1) if result.returncode == 0 and match else None
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def resolve_cleanup_version(root):
    if root.provider != "claude":
        return root.executable_version
    if root.executable_version is not None and not getattr(root, "_detected_version", False):
        return root.executable_version
    root._detected_version = True
    root.executable_version = None
    executable = root.executable_path
    try:
        if not executable or not executable.is_absolute() or not executable.is_file():
            return None
        executable = executable.resolve()
        info = executable.stat()
        if (
            info.st_uid not in (os.getuid(), 0)
            or info.st_mode & 0o022
            or not os.access(executable, os.X_OK)
        ):
            return None
        root.executable_version = _claude_version(
            str(executable), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
        )
    except OSError:
        pass
    return root.executable_version
