"""Manager-owned SQLite catalog. Native databases never pass through this writer."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import threading
import uuid
import zlib
from contextlib import contextmanager
from pathlib import Path

from .config import ensure_private
from .models import Failure, Session, now_ms, public


def unpack(value):
    return zlib.decompress(value).decode() if isinstance(value, bytes) else value


def session_payload(payload):
    try:
        return Session.from_dict(json.loads(payload))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Failure("catalog_record_invalid", 6) from None


SCHEMA = """
CREATE TABLE IF NOT EXISTS roots(root_id TEXT PRIMARY KEY, payload TEXT NOT NULL, as_of INTEGER, state TEXT);
CREATE TABLE IF NOT EXISTS sessions(
 uid TEXT PRIMARY KEY, namespace TEXT NOT NULL, native_id TEXT, payload TEXT NOT NULL,
 hidden INTEGER NOT NULL DEFAULT 0, presence TEXT NOT NULL DEFAULT 'present',
 UNIQUE(namespace,native_id));
CREATE TABLE IF NOT EXISTS locations(
 uid TEXT NOT NULL REFERENCES sessions(uid), root_id TEXT NOT NULL REFERENCES roots(root_id),
 locator TEXT NOT NULL, generation TEXT NOT NULL, PRIMARY KEY(uid,root_id,locator));
CREATE TABLE IF NOT EXISTS generations(
 id TEXT PRIMARY KEY, root_id TEXT NOT NULL REFERENCES roots(root_id), complete INTEGER, as_of INTEGER);
PRAGMA user_version=1;
"""


class Catalog:
    def __init__(self, data_dir):
        self.data_dir = ensure_private(Path(data_dir))
        self.path = self.data_dir / "catalog.sqlite3"
        descriptor = os.open(
            self.data_dir / "catalog.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Failure("unsafe_catalog_lock", 6)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._initialize()
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _initialize(self):
        if self.path.is_symlink():
            raise Failure("unsafe_catalog", 6)
        if self.path.exists():
            info = self.path.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Failure("unsafe_catalog", 6)
        new = not self.path.exists() or self.path.stat().st_size == 0
        if not new:
            with self.path.open("rb") as stream:
                header = stream.read(100)
            if len(header) != 100 or header[:16] != b"SQLite format 3\0":
                raise Failure("catalog_corrupt", 6)
            if (
                int.from_bytes(header[68:72], "big") != 0x53455353
                or int.from_bytes(header[60:64], "big") > 1
            ):
                raise Failure("unsupported_catalog_schema", 4)
        self.connection = sqlite3.connect(self.path, timeout=5)
        if self.connection.execute("PRAGMA user_version").fetchone()[0] > 1:
            self.connection.close()
            raise Failure("unsupported_catalog_schema", 4)
        if new:
            self.connection.execute("PRAGMA application_id=1397052243")
            self.connection.execute("PRAGMA user_version=1")
            self.connection.commit()
        self.path.chmod(0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function("unpack", 1, unpack, deterministic=True)
        self.connection.create_function(
            "casefold", 1, lambda value: (value or "").casefold(), deterministic=True
        )
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA cache_size=-65536")
        self.connection.execute("PRAGMA temp_store=MEMORY")
        self.connection.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._private_sidecars()
        self._history_schema()
        self._usage_schema()
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS jsonl_cursors(root_id TEXT,path TEXT,uid TEXT REFERENCES sessions(uid),payload BLOB,PRIMARY KEY(root_id,path))"
        )
        for table in ("generations", "locations"):
            if "payload" not in {
                r[1] for r in self.connection.execute(f"PRAGMA table_info({table})")
            }:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN payload TEXT")
        if "current_trash_id" not in {
            r[1] for r in self.connection.execute("PRAGMA table_info(sessions)")
        }:
            self.connection.execute("ALTER TABLE sessions ADD COLUMN current_trash_id TEXT")
        self.connection.commit()

    def _private_sidecars(self):
        for suffix in ("-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + suffix)
            if sidecar.exists():
                sidecar.chmod(0o600)

    @contextmanager
    def writer(self):
        with self._lock, self.connection:
            yield self.connection
        self._private_sidecars()

    @contextmanager
    def reader(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    def publish(
        self,
        root,
        sessions,
        *,
        complete,
        reason=None,
        histories=None,
        usages=None,
        scan=None,
        cursors=None,
    ):
        generation, observed = str(uuid.uuid4()), now_ms()
        if scan is not None and scan.finished_at is not None:
            observed = scan.finished_at
        from .models import ScanGeneration

        phase_states = {
            field: ("complete" if complete else "unavailable")
            if not sessions
            else "complete"
            if all(getattr(s, field) == "complete" for s in sessions)
            else "partial"
            for field in ("history_state", "search_state", "usage_state")
        }
        details = ScanGeneration(
            generation,
            root.root_id,
            state="complete" if complete else "partial",
            started_at=scan.started_at if scan else observed,
            finished_at=(scan.finished_at or observed) if scan else observed,
            enumeration="partial" if not complete else "complete",
            history=phase_states["history_state"],
            search=phase_states["search_state"],
            usage=phase_states["usage_state"],
            source_revision_range=scan.source_revision_range if scan else [],
            diagnostics=[reason] if reason else [],
        )
        with self.writer() as db:
            previous_root = db.execute(
                "SELECT as_of FROM roots WHERE root_id=?", (root.root_id,)
            ).fetchone()
            data_as_of = observed if complete else previous_root[0] if previous_root else None
            root.health = "complete" if complete else "partial"
            root.last_scan_id = generation
            db.execute(
                "INSERT INTO roots VALUES (?,?,?,?) ON CONFLICT(root_id) DO UPDATE SET payload=excluded.payload,as_of=excluded.as_of,state=excluded.state",
                (
                    root.root_id,
                    json.dumps(public(root)),
                    data_as_of,
                    "complete" if complete else reason or "partial",
                ),
            )
            db.execute(
                "INSERT INTO generations(id,root_id,complete,as_of,payload) VALUES (?,?,?,?,?)",
                (generation, root.root_id, complete, observed, json.dumps(public(details))),
            )
            for session in sessions:
                previous = db.execute(
                    "SELECT payload,hidden,presence FROM sessions WHERE uid=?",
                    (session.session_uid,),
                ).fetchone()
                if previous:
                    session.hidden = bool(previous["hidden"])
                active_roots = getattr(session, "_identity_root_ids", [root.root_id])
                incoming_root = session.root_id
                native_verified = getattr(session, "_native_history_verified", False)
                native = (
                    json.dumps(
                        {
                            "session": public(session),
                            "cycle": getattr(root, "_scan_cycle", None),
                            "stage": scan.stage if scan else "complete",
                        }
                    )
                    if len(active_roots) > 1
                    else None
                )
                # Store per-location native evidence before applying aggregate guards.
                # INSERT session first satisfies the existing location foreign key.
                db.execute(
                    "INSERT OR IGNORE INTO sessions(uid,namespace,native_id,payload,hidden,presence) VALUES (?,?,?,?,?,?)",
                    (
                        session.session_uid,
                        session.namespace_id,
                        session.native_id,
                        json.dumps(public(session)),
                        session.hidden,
                        session.presence,
                    ),
                )
                db.execute(
                    "INSERT INTO locations(uid,root_id,locator,generation,payload) VALUES (?,?,?,?,?) ON CONFLICT(uid,root_id,locator) DO UPDATE SET generation=excluded.generation,payload=excluded.payload",
                    (session.session_uid, root.root_id, session.locator, generation, native),
                )
                if len(active_roots) > 1:
                    chosen = self._alias_session(
                        db, session, active_roots, getattr(root, "_scan_cycle", None)
                    )
                    if (
                        chosen.root_id == incoming_root
                        and chosen.extra.get("identity_conflict") != "identity_conflict"
                        and hasattr(session, "_prepared_chunks")
                    ):
                        chosen._prepared_chunks = session._prepared_chunks
                    session = chosen
                session.current_generation = generation
                if previous:
                    session.hidden = bool(previous["hidden"])
                    if previous["presence"] in ("trashed", "purged") and not (
                        native_verified
                        and session.root_id == incoming_root
                        and not session.extra.get("identity_conflict")
                    ):
                        session.presence = previous["presence"]
                self._save_session(db, session)
                if session.root_id != incoming_root:
                    continue  # Late metadata must not replace the selected copy's history.
                if session.extra.get("identity_conflict") == "identity_conflict":
                    from .models import HistoryResult

                    if histories is not None:
                        histories[session.session_uid] = HistoryResult(
                            [], "unavailable", "identity_conflict"
                        )
                    db.execute(
                        "DELETE FROM usage_memberships WHERE uid=? OR origin_uid=?",
                        (session.session_uid, session.session_uid),
                    )
                    db.execute("DELETE FROM usage_snapshots WHERE uid=?", (session.session_uid,))
                if histories and session.session_uid in histories:
                    self._replace_history(db, session, histories[session.session_uid])
            if usages:
                for session in sessions:
                    if (
                        session.session_uid in usages
                        and (chosen := self.get(session.session_uid)).root_id == root.root_id
                        and chosen.extra.get("identity_conflict") != "identity_conflict"
                    ):
                        self._replace_usage(db, session, usages[session.session_uid])
            if complete:
                affected = [
                    r[0]
                    for r in db.execute(
                        "SELECT DISTINCT uid FROM locations WHERE root_id=? AND generation<>?",
                        (root.root_id, generation),
                    )
                ]
                db.execute(
                    "DELETE FROM locations WHERE root_id=? AND generation<>?",
                    (root.root_id, generation),
                )
                for uid in affected:
                    current = self.get(uid)
                    active = getattr(root, "_identity_root_ids", [root.root_id])
                    if len(active) > 1:
                        revised = self._alias_session(
                            db, current, active, getattr(root, "_scan_cycle", None)
                        )
                        revised.hidden, revised.presence = current.hidden, current.presence
                        self._save_session(db, revised)
                db.execute(
                    "UPDATE sessions SET presence='missing' WHERE presence IN ('present','source_unavailable','missing') AND uid NOT IN (SELECT uid FROM locations)"
                )
            owners = {s.locator: s for s in sessions} if cursors else {}
            for path, checkpoint in (cursors or {}).items():
                owner = owners.get(path)
                if owner is None:
                    parent = owners.get(str(Path(path).parent))
                    owner = parent if parent is not None and parent.provider == "grok" else None
                if owner:
                    db.execute(
                        "INSERT OR REPLACE INTO jsonl_cursors VALUES (?,?,?,?)",
                        (root.root_id, path, owner.session_uid, checkpoint),
                    )
        return generation

    @staticmethod
    def _save_session(db, session):
        db.execute(
            "UPDATE sessions SET payload=?,presence=?,current_trash_id=CASE WHEN ?='present' THEN NULL ELSE current_trash_id END WHERE uid=?",
            (json.dumps(public(session)), session.presence, session.presence, session.session_uid),
        )

    def _alias_session(self, db, incoming, active_roots, cycle):
        from .models import Capability

        evidence = []
        for row in db.execute(
            "SELECT root_id,payload FROM locations WHERE uid=?", (incoming.session_uid,)
        ):
            if row["root_id"] not in active_roots:
                continue
            if row["payload"]:
                item = json.loads(row["payload"])
                item["session"] = Session.from_dict(item["session"])
            else:
                item = {"session": incoming, "cycle": None, "stage": "metadata"}
            evidence.append(item)
        if not evidence:
            return incoming

        def full(item):
            return (
                item["stage"] == "complete"
                and item["session"].extra.get("identity_digest_version") == "2"
                and bool(item["session"].extra.get("identity_digest"))
            )

        best = max(
            evidence,
            key=lambda item: (
                full(item),
                item["cycle"] == cycle,
                item["session"].root_id == incoming.root_id,
            ),
        )
        chosen = best["session"]
        signatures = {
            e["session"].root_id: e["session"].extra.get("identity_digest")
            if full(e) and e["cycle"] == cycle
            else None
            for e in evidence
        }
        chosen.extra["identity_signatures"] = signatures
        chosen.extra.pop("alias_bindings", None)
        chosen.extra.pop("identity_conflict", None)
        if len(evidence) < 2:
            return chosen
        pending = None in signatures.values()
        conflict = not pending and len(set(signatures.values())) > 1
        if pending or conflict:
            reason = "identity_conflict" if conflict else "identity_binding_unverified"
            chosen.extra["identity_conflict"] = reason
            for name in ("resume", "cleanup"):
                chosen.capabilities[name] = Capability("unsafe", reason)
            for name in ("history", "search", "usage"):
                if conflict:
                    setattr(chosen, name + "_state", "unavailable")
                    chosen.capabilities[name] = Capability("unsafe", reason)
                elif getattr(chosen, name + "_state") == "complete":
                    setattr(chosen, name + "_state", "partial")
            if conflict:
                chosen.title, chosen.preview, chosen.cwd = (
                    "Conflicting session locations",
                    None,
                    None,
                )
                chosen.project_id = chosen.model = None
                db.execute("DELETE FROM event_memberships WHERE uid=?", (chosen.session_uid,))
                db.execute("DELETE FROM chunks WHERE uid=?", (chosen.session_uid,))
        else:
            chosen.capabilities["cleanup"] = Capability(
                "unavailable", "multiple_locations_unverified"
            )
            chosen.extra["alias_bindings"] = [
                {
                    "root": json.loads(
                        db.execute(
                            "SELECT payload FROM roots WHERE root_id=?", (e["session"].root_id,)
                        ).fetchone()[0]
                    ),
                    "fingerprint": e["session"].fingerprint,
                    "locator": e["session"].locator,
                }
                for e in evidence
            ]
        return chosen

    def invalidate_aliases(self, roots, cycle):
        """A previous cycle's agreement is not proof for a refresh in flight."""
        with self.writer() as db:
            for root in roots:
                active = root._identity_root_ids
                if len(active) < 2:
                    continue
                uids = [
                    r[0]
                    for r in db.execute(
                        "SELECT uid FROM locations WHERE root_id=? AND uid IN (SELECT uid FROM locations GROUP BY uid HAVING COUNT(*)>1)",
                        (root.root_id,),
                    )
                ]
                for uid in uids:
                    current = self.get(uid)
                    revised = self._alias_session(db, current, active, cycle)
                    revised.hidden, revised.presence = current.hidden, current.presence
                    self._save_session(db, revised)

    def sessions(self, *, include_missing=False):
        sql = "SELECT payload,hidden,presence FROM sessions"
        if not include_missing:
            sql += " WHERE presence IN ('present','source_unavailable')"
        result = []
        for row in self.connection.execute(sql):
            session = session_payload(row["payload"])
            session.hidden, session.presence = bool(row["hidden"]), row["presence"]
            result.append(session)
        return result

    def get(self, selector):
        prefix = selector[2:] if selector.startswith("s-") else selector
        rows = self.connection.execute(
            "SELECT payload,hidden,presence FROM sessions WHERE uid>=? AND uid<?",
            (prefix, prefix + "\uffff"),
        )
        matches = []
        for row in rows:
            session = session_payload(row["payload"])
            session.hidden, session.presence = bool(row["hidden"]), row["presence"]
            if session.display_id.startswith(selector) or session.session_uid == selector:
                matches.append(session)
        if len(matches) != 1:
            raise Failure("ambiguous_session_id" if matches else "session_not_found", 2)
        return matches[0]

    def hide(self, ids, hidden):
        with self.writer() as db:
            for uid in ids:
                db.execute("UPDATE sessions SET hidden=? WHERE uid=?", (hidden, uid))

    def root_states(self):
        return [dict(row) for row in self.connection.execute("SELECT * FROM roots")]

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _history_schema(self):
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS index_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        layout = self.connection.execute(
            "SELECT value FROM index_meta WHERE key='fts_layout'"
        ).fetchone()
        rebuild = not layout or layout[0] != "2"
        if rebuild:
            self.connection.executescript(
                "DROP TRIGGER IF EXISTS chunks_insert; DROP TRIGGER IF EXISTS chunks_delete; DROP TABLE IF EXISTS search_fts;"
            )
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS events(event_uid TEXT PRIMARY KEY,payload TEXT NOT NULL,body BLOB);
        CREATE TABLE IF NOT EXISTS event_memberships(uid TEXT REFERENCES sessions(uid), event_uid TEXT REFERENCES events(event_uid), ordinal INTEGER,context TEXT, PRIMARY KEY(uid,event_uid));
        CREATE INDEX IF NOT EXISTS membership_event ON event_memberships(event_uid);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,uid TEXT REFERENCES sessions(uid),field_kind TEXT,folded_text TEXT NOT NULL,candidate_text TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS chunks_session ON chunks(uid);
        CREATE VIEW IF NOT EXISTS history_search_content AS SELECT id,candidate_text FROM chunks WHERE field_kind IN ('user','assistant','tool_call','tool_result','system','unsupported');
        CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(candidate_text,content='history_search_content',content_rowid='id',tokenize='trigram',detail='none');
        CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON chunks WHEN new.field_kind IN ('user','assistant','tool_call','tool_result','system','unsupported') BEGIN INSERT INTO search_fts(rowid,candidate_text) VALUES(new.id,new.candidate_text); END;
        CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks WHEN old.field_kind IN ('user','assistant','tool_call','tool_result','system','unsupported') BEGIN INSERT INTO search_fts(search_fts,rowid,candidate_text) VALUES('delete',old.id,old.candidate_text); END;
        CREATE TABLE IF NOT EXISTS index_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        if rebuild:
            self.connection.execute("INSERT INTO search_fts(search_fts) VALUES ('rebuild')")
            self.connection.execute("INSERT OR REPLACE INTO index_meta VALUES ('fts_layout','2')")
        membership_columns = {
            r[1] for r in self.connection.execute("PRAGMA table_info(event_memberships)")
        }
        if "context" not in membership_columns:
            self.connection.execute("ALTER TABLE event_memberships ADD COLUMN context TEXT")
        event_columns = {r[1] for r in self.connection.execute("PRAGMA table_info(events)")}
        if "body" not in event_columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN body BLOB")
        if "logical_uid" not in event_columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN logical_uid TEXT")
            self.connection.execute("UPDATE events SET logical_uid=event_uid")
        self.connection.execute("CREATE INDEX IF NOT EXISTS event_identity ON events(logical_uid)")
        from .models import NORMALIZER_VERSION

        old = self.connection.execute(
            "SELECT value FROM index_meta WHERE key='normalizer'"
        ).fetchone()
        if old and old[0] != NORMALIZER_VERSION:
            with self.writer() as db:
                db.execute("DELETE FROM chunks")
                db.execute(
                    "UPDATE sessions SET payload=json_set(payload,'$.search_state','stale','$.history_state','stale') WHERE presence IN ('present','source_unavailable','missing')"
                )
        self.connection.execute(
            "INSERT OR REPLACE INTO index_meta VALUES ('normalizer',?)", (NORMALIZER_VERSION,)
        )
        self.connection.commit()
        self.index_valid = (
            self.connection.execute(
                "SELECT 1 FROM sessions WHERE presence IN ('present','source_unavailable') AND json_extract(payload,'$.search_state')='stale' LIMIT 1"
            ).fetchone()
            is None
        )

    def replace_history(self, session, result):
        with self.writer() as db:
            self._replace_history(db, session, result)

    def _replace_history(self, db, session, result):
        from .models import identity

        db.execute("DELETE FROM event_memberships WHERE uid=?", (session.session_uid,))
        db.execute("DELETE FROM chunks WHERE uid=?", (session.session_uid,))
        for event in result.events:
            payload = public(event)
            payload["text"] = None
            body = getattr(event, "_compressed_body", None)
            if body is None and event.text is not None:
                body = zlib.compress(event.text.encode(), 1)
            # Logical native identity and observed content revision are separate.
            # Refreshing one fork/copy must never rewrite another one's snapshot.
            stored_uid = identity(
                "event-revision",
                event.event_uid,
                event.role,
                hashlib.sha256(body or b"").hexdigest(),
            )
            conflicts = {
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT m.uid FROM events e JOIN event_memberships m USING(event_uid) WHERE e.logical_uid=? AND (e.body IS NOT ? OR json_extract(unpack(e.payload),'$.role')<>?)",
                    (event.event_uid, body, event.role),
                )
            }
            if conflicts:
                conflicts.add(session.session_uid)
                session.history_state = session.search_state = "partial"
                for uid in conflicts:
                    db.execute(
                        "UPDATE sessions SET payload=json_set(payload,'$.history_state','partial','$.search_state','partial','$.extra.history_conflict','shared_event_revision_conflict') WHERE uid=?",
                        (uid,),
                    )
            db.execute(
                "INSERT INTO events(event_uid,payload,body,logical_uid) VALUES (?,?,?,?) ON CONFLICT(event_uid) DO NOTHING",
                (
                    stored_uid,
                    zlib.compress(json.dumps(payload, ensure_ascii=False).encode(), 1),
                    body,
                    event.event_uid,
                ),
            )
            db.execute(
                "INSERT OR REPLACE INTO event_memberships(uid,event_uid,ordinal,context) VALUES (?,?,?,?)",
                (
                    session.session_uid,
                    stored_uid,
                    event.ordinal,
                    json.dumps(
                        {
                            key: value
                            for key, value in payload.items()
                            if key not in ("event_uid", "role", "ordinal", "text")
                        }
                    ),
                ),
            )
            if event.text and not hasattr(session, "_prepared_chunks"):
                self._add_chunk(db, session.session_uid, event.role, event.text, body)
        if hasattr(session, "_prepared_chunks"):
            db.executemany(
                "INSERT INTO chunks(uid,field_kind,folded_text,candidate_text) VALUES (?,?,?,?)",
                [(session.session_uid, *row) for row in session._prepared_chunks],
            )
        else:
            for key in ("title", "preview", "cwd", "native_id", "display_id"):
                value = getattr(session, key)
                if value:
                    self._add_chunk(db, session.session_uid, key, value)

    def events(self, uid, offset=0, limit=100):
        rows = self.connection.execute(
            "SELECT e.payload,e.body,m.ordinal,m.context FROM events e JOIN event_memberships m USING(event_uid) WHERE m.uid=? ORDER BY m.ordinal,e.event_uid LIMIT ? OFFSET ?",
            (uid, limit, offset),
        )
        result = []
        for row in rows:
            value = json.loads(unpack(row[0]))
            value["ordinal"] = row[2]
            if row[3]:
                value.update(json.loads(row[3]))
            if row[1] is not None:
                value["text"] = unpack(row[1])
            result.append(value)
        return result

    def match_context(self, uid, query):
        from .search import literal_context

        if not query:
            return None
        row = self.connection.execute(
            "SELECT e.payload,e.body,m.ordinal FROM event_memberships m JOIN events e USING(event_uid) WHERE m.uid=? AND instr(casefold(unpack(e.body)),?)>0 ORDER BY m.ordinal,e.event_uid LIMIT 1",
            (uid, query.casefold()),
        ).fetchone()
        if row:
            event = json.loads(unpack(row[0]))
            return {
                "field": event["role"],
                "event_uid": event["event_uid"],
                "ordinal": row[2],
                "text": literal_context(unpack(row[1]), query),
            }
        session = self.get(uid)
        for field in ("title", "preview", "cwd", "native_id", "display_id"):
            text = getattr(session, field)
            if text and query.casefold() in text.casefold():
                return {"field": field, "text": literal_context(text, query)}
        return None

    def matching_ids(self, query):
        folded = query.casefold()
        if not folded:
            return {s.session_uid for s in self.sessions()}
        if "\0" in folded:
            rows = self.connection.execute(
                "SELECT DISTINCT uid FROM chunks WHERE instr(unpack(folded_text),?)>0", (folded,)
            )
        elif len(folded) < 3:
            rows = self.connection.execute(
                "SELECT DISTINCT uid FROM chunks WHERE instr(candidate_text,?)>0", (folded,)
            )
        else:
            grams = list(dict.fromkeys(folded[i : i + 3] for i in range(len(folded) - 2)))[:64]
            term = " AND ".join('"' + g.replace('"', '""') + '"' for g in grams)
            rows = self.connection.execute(
                "SELECT DISTINCT c.uid FROM search_fts f JOIN chunks c ON c.id=f.rowid WHERE search_fts MATCH ? AND instr(unpack(c.folded_text),?)>0 UNION SELECT DISTINCT uid FROM chunks WHERE field_kind IN ('title','preview','cwd','native_id','display_id') AND instr(unpack(folded_text),?)>0",
                (term, folded, folded),
            )
        return {r[0] for r in rows}

    def _add_chunk(self, db, uid, kind, text, original_blob=None):
        from .search import prepare_chunk

        db.execute(
            "INSERT INTO chunks(uid,field_kind,folded_text,candidate_text) VALUES (?,?,?,?)",
            (uid, *prepare_chunk(kind, text, original_blob)),
        )

    def _usage_schema(self):
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS usage_facts(fact_uid TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS usage_memberships(uid TEXT REFERENCES sessions(uid),fact_uid TEXT REFERENCES usage_facts(fact_uid),origin_uid TEXT REFERENCES sessions(uid),PRIMARY KEY(uid,fact_uid,origin_uid));
        CREATE INDEX IF NOT EXISTS usage_origin ON usage_memberships(origin_uid);
        CREATE TABLE IF NOT EXISTS usage_snapshots(uid TEXT REFERENCES sessions(uid),scope TEXT,epoch TEXT,payload TEXT,PRIMARY KEY(uid,scope,epoch));
        CREATE TABLE IF NOT EXISTS context_metrics(uid TEXT PRIMARY KEY REFERENCES sessions(uid),payload TEXT);
        """)

    def replace_usage(self, session, result):
        with self.writer() as db:
            self._replace_usage(db, session, result)

    def _replace_usage(self, db, session, result):
        from .models import TOKEN_CATEGORIES, UsageFact

        db.execute("DELETE FROM usage_memberships WHERE origin_uid=?", (session.session_uid,))
        db.execute("DELETE FROM usage_snapshots WHERE uid=?", (session.session_uid,))
        db.execute("DELETE FROM context_metrics WHERE uid=?", (session.session_uid,))
        for fact in result.facts:
            row = db.execute(
                "SELECT payload FROM usage_facts WHERE fact_uid=?", (fact.fact_uid,)
            ).fetchone()
            if row:
                old = UsageFact(**json.loads(row[0]))
                old_values = [getattr(old, key) for key in TOKEN_CATEGORIES]
                new_values = [getattr(fact, key) for key in TOKEN_CATEGORIES]
                if old_values != new_values:
                    if fact.provider == "claude" and all(
                        a is None or (b is not None and b >= a)
                        for a, b in zip(old_values, new_values, strict=True)
                    ):
                        pass
                    elif fact.provider == "claude" and all(
                        b is None or (a is not None and a >= b)
                        for a, b in zip(old_values, new_values, strict=True)
                    ):
                        fact = old
                    else:
                        fact = UsageFact(
                            **{
                                **public(old),
                                **{key: None for key in TOKEN_CATEGORIES},
                                "completeness": "partial",
                            }
                        )
            db.execute(
                "INSERT INTO usage_facts VALUES (?,?) ON CONFLICT(fact_uid) DO UPDATE SET payload=excluded.payload",
                (fact.fact_uid, json.dumps(public(fact))),
            )
        for membership in result.memberships:
            if db.execute(
                "SELECT 1 FROM sessions WHERE uid=?", (membership.session_uid,)
            ).fetchone():
                db.execute(
                    "INSERT OR IGNORE INTO usage_memberships VALUES (?,?,?)",
                    (membership.session_uid, membership.fact_uid, session.session_uid),
                )
        for snapshot in result.snapshots:
            db.execute(
                "INSERT OR REPLACE INTO usage_snapshots VALUES (?,?,?,?)",
                (
                    snapshot.session_uid,
                    snapshot.accounting_scope,
                    snapshot.epoch,
                    json.dumps(public(snapshot)),
                ),
            )
        if result.context_metrics:
            db.execute(
                "INSERT OR REPLACE INTO context_metrics VALUES (?,?)",
                (session.session_uid, json.dumps(public(result.context_metrics))),
            )

    def usage(self, ids):
        from .models import UsageFact, UsageSnapshot

        if not ids:
            return [], {}, []
        placeholders = ",".join("?" for _ in ids)
        facts = {}
        members = {}
        for row in self.connection.execute(
            f"SELECT f.fact_uid,f.payload,m.uid FROM usage_facts f JOIN usage_memberships m USING(fact_uid) WHERE m.uid IN ({placeholders})",
            ids,
        ):
            facts[row["fact_uid"]] = UsageFact(**json.loads(row["payload"]))
            members.setdefault(row["fact_uid"], set()).add(row["uid"])
        snapshots = [
            UsageSnapshot(**json.loads(row[0]))
            for row in self.connection.execute(
                f"SELECT payload FROM usage_snapshots WHERE uid IN ({placeholders})", ids
            )
        ]
        return list(facts.values()), members, snapshots
