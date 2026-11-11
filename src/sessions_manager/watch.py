"""TUI-owned stat observations and injectable refresh deadlines; no native reads."""

import os
import stat
import time

from .sources.base import source_directory


def observe_roots(roots):
    def stamp(info):
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def walk(fd, prefix, result, depth=0):
        if depth > 64:
            raise OSError("source nesting limit")
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                relative = prefix + (entry.name,)
                result.append((relative, stamp(info)))
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(
                        entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                    try:
                        if stamp(os.fstat(child)) != stamp(info):
                            raise OSError("source directory changed")
                        walk(child, relative, result, depth + 1)
                    finally:
                        os.close(child)

    observations = {}
    for root in roots:
        try:
            with source_directory(root.path, root.path) as fd:
                result = [((), stamp(os.fstat(fd)))]
                walk(fd, (), result)
                observations[root.root_id] = tuple(sorted(result))
        except OSError:
            observations[root.root_id] = None
    return observations


class RefreshSchedule:
    INTERVAL = 5
    RETRY = 30

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.next_poll = clock() + self.INTERVAL
        self.observations = {}
        self.retry_at = {}

    def changed(self, roots, observations):
        now = self.clock()
        providers = set()
        for root in roots:
            observation = observations[root.root_id]
            retry = self.retry_at.get(root.provider)
            changed = (
                root.root_id not in self.observations
                or self.observations[root.root_id] != observation
            )
            if (retry is not None and now >= retry) or (changed and retry is None):
                providers.add(root.provider)
            self.observations[root.root_id] = observation
        return providers

    def finished(self, outcomes):
        now = self.clock()
        for provider, complete in outcomes.items():
            if complete:
                self.retry_at.pop(provider, None)
            else:
                self.retry_at[provider] = now + self.RETRY
        self.next_poll = min(
            [
                now + self.INTERVAL,
                *(deadline for deadline in self.retry_at.values() if deadline > now),
            ]
        )
