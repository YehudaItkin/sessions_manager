"""Native SQLite boundary: ordinary whitelisted tables, never repair or mutate."""

from __future__ import annotations

import sqlite3
import stat
import time
from pathlib import Path

from ..models import Failure


class NativeSQLite:
    def __init__(self, path: Path, tables: dict[str, set[str]], *, closed_snapshot=False):
        self.path, self.tables = Path(path), tables
        self.connection = None
        self.closed_snapshot, self._immutable_stamp = closed_snapshot, None
        self._bindings = {}

    @staticmethod
    def _binding(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode):
            raise Failure("source_changed", 5)
        return info.st_dev, info.st_ino

    def __enter__(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise Failure("native_store_unavailable", 3)
        with self.path.open("rb") as stream:
            header = stream.read(100)
        sidecars = [self.path.with_name(self.path.name + s) for s in ("-wal", "-shm")]
        self._bindings = {p: self._binding(p) for p in [self.path, *sidecars]}
        if len(header) >= 20 and header[18] == 2 and not all(p.is_file() for p in sidecars):
            if not self.closed_snapshot or any(p.exists() or p.is_symlink() for p in sidecars):
                raise Failure("wal_sidecars_unavailable", 3)
            from .base import fingerprint

            self._immutable_stamp = fingerprint(self.path)
        try:
            self.connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro" + ("&immutable=1" if self._immutable_stamp else ""),
                uri=True,
                timeout=0.1,
            )
            self.connection.row_factory = sqlite3.Row
            self.connection.enable_load_extension(False)
            self.connection.execute("PRAGMA query_only=ON")
            self.connection.execute("PRAGMA trusted_schema=OFF")
            self.connection.execute("PRAGMA busy_timeout=100")
            self.connection.execute("PRAGMA mmap_size=1073741824")
            # Pin schema, metadata and every graph/table SELECT to one native
            # snapshot. Independent databases still have separate snapshots.
            self.connection.execute("BEGIN")
            table_types = {
                r[1]: r[2] for r in self.connection.execute("PRAGMA table_list") if r[0] == "main"
            }
            for name, columns in self.tables.items():
                row = self.connection.execute(
                    "SELECT type FROM sqlite_master WHERE name=?", (name,)
                ).fetchone()
                if not row or row[0] != "table" or table_types.get(name) != "table":
                    raise Failure("unsupported_native_schema", 3)
                actual = {
                    r[1] for r in self.connection.execute('PRAGMA table_info("' + name + '")')
                }
                if not columns <= actual:
                    raise Failure("unsupported_native_schema", 3)
            self.connection.set_authorizer(self._authorize)
            return self
        except Exception:
            if self.connection:
                self.connection.close()
            raise

    def read(self, table, columns, *, key=None, value=None, order=None):
        if table not in self.tables or not set(columns) <= self.tables[table]:
            raise Failure("unsupported_native_schema", 3)
        if key and key not in self.tables[table]:
            raise Failure("unsupported_native_schema", 3)
        if order and order not in self.tables[table]:
            raise Failure("unsupported_native_schema", 3)
        sql = "SELECT " + ",".join('"' + c + '"' for c in columns) + ' FROM "' + table + '"'
        params = ()
        if key:
            sql += ' WHERE "' + key + '"=?'
            params = (value,)
        if order:
            sql += ' ORDER BY "' + order + '"'
        for attempt in range(3):
            try:
                return [dict(row) for row in self.connection.execute(sql, params)]
            except sqlite3.OperationalError:
                if attempt == 2:
                    raise Failure("native_store_busy", 3) from None
                time.sleep(0.02)

    def __exit__(self, *args):
        if self.connection:
            self.connection.close()
        if any(self._binding(path) != binding for path, binding in self._bindings.items()):
            raise Failure("source_changed", 5)
        if self._immutable_stamp:
            from .base import fingerprint

            if fingerprint(self.path) != self._immutable_stamp or any(
                self.path.with_name(self.path.name + s).exists() for s in ("-wal", "-shm")
            ):
                raise Failure("source_changed", 5)

    def _authorize(self, action, first, second, database, origin):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION):
            return sqlite3.SQLITE_OK
        if (
            action == sqlite3.SQLITE_READ
            and database == "main"
            and first in {*self.tables, "sqlite_master", "sqlite_schema"}
        ):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA:
            if second is None and first in {
                "query_only",
                "trusted_schema",
                "data_version",
                "schema_version",
                "user_version",
                "mmap_size",
            }:
                return sqlite3.SQLITE_OK
            if first == "table_info" and second in self.tables:
                return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
