"""Bounded readers; the caller alone publishes to the manager writer."""

import importlib
import multiprocessing
import sqlite3
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait

from .models import Capability, Failure, location_key, now_ms
from .sources.base import ScanResult

READ_ERRORS = (OSError, Failure, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error)


def adapter(root):
    return importlib.import_module("sessions_manager.sources." + root.provider).Adapter(root)


def scan_metadata(argument):
    root, cached = argument
    started = now_ms()
    revisions = dict(getattr(root, "_lifecycle_revisions", {}))
    try:
        if cached and not root.path.exists():
            return ScanResult(complete=False, reason="source_unavailable")
        reader = adapter(root)
        reader.metadata_only = True
        result = reader.discover()
        result.lifecycle_revisions = revisions
        counts = Counter(s.session_uid for s in result.sessions)
        for session in result.sessions:
            session._identity_root_ids = getattr(root, "_identity_root_ids", [root.root_id])
            old = cached.get(session.session_uid)
            session._compare_identity = counts[session.session_uid] > 1 or bool(
                old and old.extra.get("identity_signatures")
            )
            session.history_state = session.search_state = session.usage_state = "partial"
            for name in ("history", "search", "usage", "resume", "cleanup", "archive", "unarchive"):
                session.capabilities[name] = Capability("unavailable", "scan_pending")
        result.stage = "metadata"
        result.complete = False
        result.reason = result.reason or "scan_pending"
        return result
    except READ_ERRORS:
        return ScanResult(complete=False, reason="source_unavailable", stage="metadata")
    finally:
        # Both successful and failed phases carry actual reader time bounds.
        if "result" in locals():
            result.started_at, result.finished_at = started, now_ms()


def scan_root(argument):
    root, cached = argument
    started = now_ms()
    revisions = dict(getattr(root, "_lifecycle_revisions", {}))
    try:
        if cached and not root.path.exists():
            return ScanResult(complete=False, reason="source_unavailable")
        reader = adapter(root)
        from .sources.jsonl_cursor import JSONLCursor

        reader.jsonl_cache = JSONLCursor(getattr(root, "_jsonl_cursors", {}))
        result = reader.discover()
        result.lifecycle_revisions = revisions
        from .activity import observe

        observe(root, result.sessions)
        result.histories = {}
        result.usages = {}
        from .models import NORMALIZER_VERSION, Capability
        from .sources.base import prepare_cleanup_bundle

        cleanup_checks = {}
        counts = Counter(s.session_uid for s in result.sessions)
        for session in result.sessions:
            old = cached.get(session.session_uid)
            session._identity_root_ids = getattr(root, "_identity_root_ids", [root.root_id])
            compare_identity = (
                len(session._identity_root_ids) > 1
                or counts[session.session_uid] > 1
                or bool(old and old.extra.get("identity_signatures"))
            )
            session._compare_identity = compare_identity
            session._scan_data_key = (
                location_key(session) if counts[session.session_uid] > 1 else session.session_uid
            )
            unchanged = (
                old is not None
                and old.locator == session.locator
                and old.fingerprint == session.fingerprint
            )
            if (
                unchanged
                and old.presence == "present"
                and old.extra.get("normalizer_version") == NORMALIZER_VERSION
                and old.history_state == "complete"
                and (not compare_identity or old.extra.get("identity_digest_version") == "2")
            ):
                session.history_state, session.search_state = old.history_state, old.search_state
                session.capabilities["history"] = old.capabilities["history"]
                session.capabilities["search"] = old.capabilities["search"]
                if compare_identity:
                    session.extra["identity_digest"] = old.extra.get("identity_digest")
                    session.extra["identity_digest_version"] = "2"
            else:
                try:
                    history = reader.read_history(session)
                except READ_ERRORS:
                    history = None
                    session.history_state = session.search_state = "partial"
                    session.capabilities["history"] = session.capabilities["search"] = Capability(
                        "unavailable", "history_read_failed"
                    )
                if history is not None:
                    session.history_state = session.search_state = history.state
                    session.capabilities["history"] = session.capabilities["search"] = Capability(
                        "supported" if history.state in ("complete", "partial") else "unavailable",
                        history.reason,
                    )
                    result.histories[session._scan_data_key] = history
                    native_verified = (
                        history.state == "complete"
                        and bool(history.events)
                        and (
                            session.provider != "codex"
                            or getattr(session, "_native_history_verified", False)
                        )
                    )
                    if native_verified:
                        # Reappearance needs current native evidence, not metadata or
                        # an unchanged cached projection. Recheck rare tombstone reads.
                        if old is not None and old.presence in ("trashed", "purged"):
                            fresh = next(
                                (
                                    s
                                    for s in adapter(root).discover().sessions
                                    if s.session_uid == session.session_uid
                                ),
                                None,
                            )
                            native_verified = (
                                fresh is not None and fresh.fingerprint == session.fingerprint
                            )
                        session._native_history_verified = native_verified
                if compare_identity and history is not None and history.state == "complete":
                    import hashlib
                    import json

                    checksum = hashlib.sha256(json.dumps(session.cwd).encode())
                    for event in history.events:
                        checksum.update(
                            json.dumps(
                                [
                                    event.native_id or event.event_uid,
                                    event.role,
                                    event.text,
                                    event.parent_id,
                                    event.turn_id,
                                    event.completeness,
                                ],
                                ensure_ascii=False,
                            ).encode()
                        )
                    session.extra["identity_digest"] = checksum.hexdigest()
                    session.extra["identity_digest_version"] = "2"
            session.extra["normalizer_version"] = NORMALIZER_VERSION
            if unchanged and old.extra.get("usage_version") == "4" and old.usage_state != "partial":
                session.usage_state = old.usage_state
                session.capabilities["usage"] = old.capabilities["usage"]
            else:
                try:
                    usage = reader.read_usage(session)
                except READ_ERRORS:
                    session.usage_state = "partial"
                    session.capabilities["usage"] = Capability("unavailable", "usage_read_failed")
                else:
                    session.usage_state = usage.state
                    session.capabilities["usage"] = Capability(
                        "supported" if usage.state in ("complete", "partial") else "unavailable",
                        usage.reason,
                    )
                    result.usages[session._scan_data_key] = usage
            session.extra["usage_version"] = "4"
            try:
                prepare_cleanup_bundle(root, session, common_checks=cleanup_checks)
                session.capabilities["cleanup"] = Capability("supported")
            except READ_ERRORS as failure:
                session.capabilities["cleanup"] = Capability(
                    "unavailable",
                    failure.code if isinstance(failure, Failure) else "cleanup_read_failed",
                )
        from .storage import measure

        result.storage = measure(root)
        result.started_at, result.finished_at = started, now_ms()
        result.source_revision_range = [
            {
                "session_uid": s.session_uid,
                "before": cached[s.session_uid].fingerprint if s.session_uid in cached else None,
                "after": s.fingerprint,
            }
            for s in result.sessions
        ]
        result.jsonl_cursors = reader.jsonl_cache.checkpoints()
        return result
    except READ_ERRORS:
        return ScanResult(complete=False, reason="source_unavailable")


def scan_for_transport(root):
    import zlib

    result = scan_root(root)
    from .search import prepare_chunk

    result.text_buffers = {}
    by_uid = {session._scan_data_key: session for session in result.sessions}
    for uid, history in getattr(result, "histories", {}).items():
        session = by_uid[uid]
        session._prepared_chunks = []
        for event in history.events:
            if event.text is not None:
                body = zlib.compress(event.text.encode(), 1)
                result.text_buffers[(uid, event.event_uid)] = body
                if event.text:
                    session._prepared_chunks.append(prepare_chunk(event.role, event.text, body))
                event.text = None
        for kind in ("title", "preview", "cwd", "native_id", "display_id"):
            value = getattr(session, kind)
            if value:
                session._prepared_chunks.append(prepare_chunk(kind, value))
    return result


def prepare_scan(config, catalog, providers=None):
    from .models import PROVIDERS

    if providers and any(p not in PROVIDERS for p in providers):
        raise Failure("invalid_source", 2)
    roots = [r for r in config.roots if r.enabled and (not providers or r.provider in providers)]
    import uuid

    cycle = str(uuid.uuid4())
    for root in roots:
        root._scan_cycle = cycle
        root._lifecycle_revisions = dict(
            catalog.connection.execute(
                "SELECT uid,lifecycle_revision FROM sessions WHERE lifecycle_revision>0"
            )
        )
        root._jsonl_cursors = dict(
            catalog.connection.execute(
                "SELECT path,payload FROM jsonl_cursors WHERE root_id=?", (root.root_id,)
            )
        )
        root._identity_root_ids = [
            r.root_id for r in config.roots if r.enabled and r.namespace_id == root.namespace_id
        ]
    catalog.invalidate_aliases(roots, cycle)
    old = {s.session_uid: s for s in catalog.sessions(include_missing=True)}
    return roots, [(r, {uid: s for uid, s in old.items() if s.root_id == r.root_id}) for r in roots]


def iter_scan(arguments, cancel=None):
    if not arguments:
        return
    if cancel and cancel.is_set():
        for index in range(len(arguments)):
            yield index, ScanResult(complete=False, reason="cancelled")
        return
    executor = (
        ProcessPoolExecutor(
            max_workers=min(4, len(arguments)), mp_context=multiprocessing.get_context("spawn")
        )
        if len(arguments) > 1
        else ThreadPoolExecutor(max_workers=1)
    )
    with executor as pool:
        reader = scan_for_transport if len(arguments) > 1 else scan_root
        pending = {
            pool.submit(scan_metadata, argument): (index, True)
            for index, argument in enumerate(arguments)
        }
        while pending:
            ready, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in ready:
                index, metadata = pending.pop(future)
                try:
                    result = future.result()
                except Exception:
                    # Reader bugs/worker failures are isolated to their root. Control
                    # exceptions (KeyboardInterrupt/SystemExit) deliberately propagate.
                    result = ScanResult(
                        complete=False,
                        reason="source_reader_failed",
                        stage="metadata" if metadata else "complete",
                    )
                cancelled = cancel and cancel.is_set()
                if cancelled:
                    result = ScanResult(complete=False, reason="cancelled")
                yield index, result
                if metadata and not cancelled:
                    pending[pool.submit(reader, arguments[index])] = (index, False)


def collect_scan(arguments, cancel=None):
    scanned = [None] * len(arguments)
    for index, result in iter_scan(arguments, cancel):
        scanned[index] = result
    return scanned


def publish_scan(catalog, root, scanned):
    for uid, history in getattr(scanned, "histories", {}).items():
        for event in history.events:
            body = getattr(scanned, "text_buffers", {}).get((uid, event.event_uid))
            if body is not None:
                # Prepared search chunks and compressed bodies are already complete.
                # Decode only when displaying a requested history page.
                event._compressed_body = body
    root.reader_profile = scanned.profile
    catalog.publish(
        root,
        scanned.sessions,
        complete=scanned.complete,
        reason=scanned.reason,
        histories=getattr(scanned, "histories", None),
        usages=getattr(scanned, "usages", None),
        scan=scanned,
        cursors=getattr(scanned, "jsonl_cursors", None),
    )
    return {
        "root_id": root.root_id,
        "provider": root.provider,
        "profile": scanned.profile,
        "state": root.health,
        "reason": getattr(root, "_publication_reason", scanned.reason),
        "sessions": len(scanned.sessions),
    }


def refresh(config, catalog, *, providers=None, cancel=None):
    roots, arguments = prepare_scan(config, catalog, providers)
    receipts = [None] * len(roots)
    # Native readers continue while the sole caller/writer publishes completed roots.
    for index, result in iter_scan(arguments, cancel):
        receipts[index] = publish_scan(catalog, roots[index], result)
    return receipts
