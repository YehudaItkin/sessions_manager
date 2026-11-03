"""Human explanations only. Machine-readable failure/reason codes remain stable."""

import shlex

from .models import safe_text

_MESSAGES = {
    "insufficient_space": "There is not enough disk space for a verified backup. Free space before retrying; the original session is retained.",
    "observed_open_handle": "A process still has this session open. Close the session in its native CLI, then refresh and retry.",
    "confirmation_expired": "The operation preview expired. Prepare a fresh preview and confirm that exact selection.",
    "cleanup_profile_changed": "The native cleanup profile changed. Refresh and prepare a new preview.",
    "restore_profile_changed": "The native CLI version changed since trashing. Restore with the verified version or inspect the retained backup.",
    "cross_device_unavailable": "The source and manager trash are on different volumes. Use Hide, or configure manager data on the same volume.",
    "handle_probe_unavailable": "Open-session checks are unavailable. Check that lsof is installed and accessible before retrying cleanup.",
    "source_changed": "The session changed since it was selected. Refresh (F5) and try again.",
    "executable_changed": "The native CLI changed. Refresh (F5) and prepare the operation again.",
    "native_cascade_unbounded": "Codex archive/delete can also affect descendant sessions. Safe trash is unavailable for this profile; use Hide to remove it from the manager view.",
    "shared_dependency_unverified": "This session has a shared index or related sessions whose cleanup is not verified. Use Hide, or manage it in the native CLI.",
    "cleanup_profile_unverified": "Safe cleanup is not verified for this CLI version or session format. Check the configured executable; use Hide meanwhile.",
    "unknown_bundle_topology": "The session contains files outside the verified cleanup layout. Use Hide, or inspect it in the native CLI.",
    "cleanup_codec_unverified": "The stored session format could not be verified for safe cleanup. Use Hide meanwhile.",
    "resume_binding_unverified": "The native CLI cannot be bound reliably to this session location. Check the source executable and native home configuration.",
    "resume_cwd_unavailable": "The project directory is missing. Choose an existing directory or cancel.",
    "resume_cwd_unsupported": "Continuing this session from a different directory is not verified for this CLI. Choose its original directory or use the native CLI help below.",
    "native_executable_unavailable": "The native CLI executable is missing or is not executable. Install it or update the source configuration.",
    "unsafe_executable": "The native CLI executable has unsafe ownership or write permissions. Correct those permissions before retrying.",
    "invalid_native_record": "Some native session records could not be read. Other sessions remain available; update the native CLI and refresh.",
    "unsupported_native_schema": "This native storage format is not supported yet. Update Sessions Manager or use the native CLI.",
    "history_not_recorded": "No readable history was recorded for this session. Its metadata is still available.",
    "not_recorded": "The native CLI did not record this value; it cannot be reconstructed accurately.",
    "cursor_graph_incomplete": "Only part of the Cursor history can be decoded. Available messages are shown.",
    "session_active": "The session is active. Close it in its native CLI, then refresh and retry.",
    "workflow_not_closed": "A Claude workflow has not finished. Close or stop it in Claude before cleanup.",
    "closed_assertion_required": "Close the selected sessions and confirm they will remain closed during this operation.",
    "destination_conflict": "A session already exists at the restore location. Nothing was overwritten; inspect both copies before retrying.",
    "warp_unavailable": "Warp is not installed. Install Warp or choose Current terminal.",
    "warp_delivery_failed": "Warp did not accept the launch request. Choose Current terminal or retry after opening Warp.",
    "launch_ticket_expired": "The Warp launch request expired. Return to Sessions Manager and launch it again.",
    "invalid_arguments": "The command arguments are invalid. Run sessions --help for the available commands.",
    "invalid_config": "The configuration could not be read. Check its TOML syntax and absolute source/executable paths.",
    "io_error": "A file could not be read or written. Check access permissions and available disk space, then retry.",
    "catalog_io_error": "The manager catalog could not be accessed. Close other manager operations and check disk space and permissions.",
    "cancelled": "The operation was cancelled.",
    "internal_error": "The operation failed unexpectedly. Refresh and retry; include the error code if reporting a problem.",
}


def explain(code):
    return _MESSAGES.get(
        code,
        f"The operation could not be completed ({safe_text(code)}). Refresh and retry; include this code when reporting the problem.",
    )


def resume_guide(guide):
    return "\n".join(
        [
            explain(guide.get("reason")),
            f"Source: {safe_text(guide.get('provider'))}",
            f"Native ID: {safe_text(guide.get('native_id'))}",
            f"History location: {safe_text((guide.get('history_locator') or {}).get('path'))}",
            f"Original directory: {safe_text(guide.get('original_cwd'))}",
            f"Selected directory: {safe_text(guide.get('requested_cwd'))}",
            "Native CLI help: " + safe_text(shlex.join(guide.get("help_argv") or [])),
            "Choose another existing directory or cancel.",
        ]
    )


def human_data(value):
    """Translate displayed reasons without altering plans, tokens or JSON responses."""
    if isinstance(value, list):
        return [human_data(item) for item in value]
    if isinstance(value, dict):
        return {
            key: explain(item)
            if key in ("reason", "error") and isinstance(item, str)
            else human_data(item)
            for key, item in value.items()
        }
    return value
