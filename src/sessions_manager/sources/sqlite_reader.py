"""Native SQLite boundary: ordinary whitelisted tables, never repair or mutate."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ..models import Failure


class NativeSQLite:
    def __init__(self, path: Path, tables: dict[str, set[str]]):
        self.path, self.tables = Path(path), tables
        self.connection = None

    def __enter__(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise Failure("native_store_unavailable", 3)
        with self.path.open("rb") as stream:
            header = stream.read(100)
        if len(header) >= 20 and header[18] == 2:
            if not all(
                self.path.with_name(self.path.name + suffix).is_file()
                for suffix in ("-wal", "-shm")
            ):
                raise Failure("wal_sidecars_unavailable", 3)
        try:
            self.connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro", uri=True, timeout=0.1
            )
            self.connection.row_factory = sqlite3.Row
            self.connection.enable_load_extension(False)
            self.connection.execute("PRAGMA query_only=ON")
            self.connection.execute("PRAGMA trusted_schema=OFF")
            self.connection.execute("PRAGMA busy_timeout=100")
            self.connection.execute("PRAGMA mmap_size=268435456")
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
