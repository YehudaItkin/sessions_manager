"""Bounded readers; the caller alone publishes to the manager writer."""

import importlib
import multiprocessing
import sqlite3
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

from .models import Failure
from .sources.base import ScanResult

READ_ERRORS = (OSError, Failure, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error)


def adapter(root):
    return importlib.import_module("sessions_manager.sources." + root.provider).Adapter(root)


def scan_root(argument):
    root, cached = argument
    try:
        if cached and not root.path.exists():
            return ScanResult(complete=False, reason="source_unavailable")
        reader = adapter(root)
        result = reader.discover()
        from .activity import observe

        observe(root, result.sessions)
        result.histories = {}
        result.usages = {}
        from .models import NORMALIZER_VERSION, Capability
        from .sources.base import prepare_cleanup_bundle

        cleanup_checks = {}
        for session in result.sessions:
            old = cached.get(session.session_uid)
            session._identity_root_ids = getattr(root, "_identity_root_ids", [root.root_id])
            compare_identity = len(session._identity_root_ids) > 1
            unchanged = old is not None and old.fingerprint == session.fingerprint
            if (
                unchanged
                and old.extra.get("normalizer_version") == NORMALIZER_VERSION
                and old.history_state == "complete"
                and (not compare_identity or old.extra.get("identity_digest"))
            ):
                session.history_state, session.search_state = old.history_state, old.search_state
                session.capabilities["history"] = old.capabilities["history"]
                session.capabilities["search"] = old.capabilities["search"]
                if compare_identity:
                    session.extra["identity_digest"] = old.extra.get("identity_digest")
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
                    result.histories[session.session_uid] = history
                if compare_identity and history is not None and history.state == "complete":
                    import hashlib

                    checksum = hashlib.sha256((session.cwd or "").encode())
                    for event in history.events:
                        checksum.update((event.native_id or event.event_uid).encode())
                        checksum.update(event.role.encode())
                        checksum.update((event.text or "").encode())
                    session.extra["identity_digest"] = checksum.hexdigest()
            session.extra["normalizer_version"] = NORMALIZER_VERSION
            if unchanged and old.extra.get("usage_version") == "3" and old.usage_state != "partial":
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
                    result.usages[session.session_uid] = usage
            session.extra["usage_version"] = "3"
            try:
                prepare_cleanup_bundle(root, session, common_checks=cleanup_checks)
                session.capabilities["cleanup"] = Capability("supported")
            except READ_ERRORS as failure:
                session.capabilities["cleanup"] = Capability(
                    "unavailable",
                    failure.code if isinstance(failure, Failure) else "cleanup_read_failed",
                )
        return result
    except READ_ERRORS:
        return ScanResult(complete=False, reason="source_unavailable")


def scan_for_transport(root):
    import zlib

    result = scan_root(root)
    from .search import prepare_chunk

    result.text_buffers = {}
    by_uid = {session.session_uid: session for session in result.sessions}
    for uid, history in getattr(result, "histories", {}).items():
        session = by_uid[uid]
        session._prepared_chunks = []
        for event in history.events:
            if event.text is not None:
                body = zlib.compress(event.text.encode(), 1)
                result.text_buffers[event.event_uid] = body
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
    for root in roots:
        root._identity_root_ids = [
            r.root_id for r in config.roots if r.enabled and r.namespace_id == root.namespace_id
        ]
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
        pending = {pool.submit(reader, argument): index for index, argument in enumerate(arguments)}
        for future in as_completed(pending):
            index = pending.pop(future)
            result = future.result()
            if cancel and cancel.is_set():
                result = ScanResult(complete=False, reason="cancelled")
            yield index, result


def collect_scan(arguments, cancel=None):
    scanned = [None] * len(arguments)
    for index, result in iter_scan(arguments, cancel):
        scanned[index] = result
    return scanned


def publish_scan(catalog, root, scanned):
    for history in getattr(scanned, "histories", {}).values():
        for event in history.events:
            body = getattr(scanned, "text_buffers", {}).get(event.event_uid)
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
    )
    return {
        "root_id": root.root_id,
        "provider": root.provider,
        "profile": scanned.profile,
        "state": "complete" if scanned.complete else "partial",
        "reason": scanned.reason,
        "sessions": len(scanned.sessions),
    }


def refresh(config, catalog, *, providers=None, cancel=None):
    roots, arguments = prepare_scan(config, catalog, providers)
    receipts = [None] * len(roots)
    # Native readers continue while the sole caller/writer publishes completed roots.
    for index, result in iter_scan(arguments, cancel):
        receipts[index] = publish_scan(catalog, roots[index], result)
    return receipts
