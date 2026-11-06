"""Value types and safe public results. No provider credentials belong here."""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROVIDERS = ("codex", "claude", "cursor", "grok")
NORMALIZER_VERSION = "3/" + unicodedata.unidata_version
NAMESPACE = uuid.UUID("7875cdc8-1c78-4bc4-8345-51e66a8c26ef")
COMPLETENESS = ("complete", "partial", "unavailable", "stale")
CAPABILITY_NAMES = (
    "metadata",
    "history",
    "search",
    "resume",
    "usage",
    "cleanup",
    "archive",
    "unarchive",
)
OPERATION_STATES = (
    "preview",
    "restore_preview",
    "purge_preview",
    "backup_ready",
    "removing",
    "restoring",
    "purging",
    "trashed",
    "restored",
    "purged",
    "failed_no_change",
    "recovery_required",
    "conflict",
    "cancelled",
)


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("invalid identifier")


def _absolute_path(value):
    if not isinstance(value, (str, Path)) or "\0" in str(value) or not Path(value).is_absolute():
        raise ValueError("absolute path required")


def _milliseconds(value, *, optional=False):
    if not (value is None and optional) and type(value) is not int:
        raise ValueError("invalid UTC milliseconds")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def counter(value):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError("expected nonnegative integer or null")
    return value


def timestamp(value, *, milliseconds=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (float, int)):
            return int(value if milliseconds or value > 100_000_000_000 else value * 1000)
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return int(parsed.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return None


def annotate_dates(session, created_values, last_values):
    """Retain timezone uncertainty without inventing UTC instants for naive dates."""

    def confidence(value):
        if value is None:
            return "unknown"
        if isinstance(value, str):
            try:
                if dt.datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    return "ambiguous"
            except ValueError:
                pass
        return "known" if timestamp(value) is not None else "unknown"

    provenance, ambiguous = {}, False
    for name, values in (("created_at", created_values), ("last_activity_at", last_values)):
        values = list(values)
        uncertain = any(confidence(value) == "ambiguous" for value in values)
        ambiguous |= uncertain
        state = (
            "known"
            if getattr(session, name) is not None
            else "ambiguous"
            if uncertain
            else "unknown"
        )
        reason = (
            None
            if state == "known"
            else "timezone_not_recorded"
            if uncertain
            else "not_recorded"
            if all(value is None for value in values)
            else "invalid_timestamp"
        )
        provenance[name] = {"confidence": state, "reason": reason}
    session.extra["date_provenance"] = provenance
    session.extra["ambiguous_native_dates"] = ambiguous
    session.timezone_confidence = (
        "ambiguous"
        if ambiguous
        else "known"
        if any(v["confidence"] == "known" for v in provenance.values())
        else "unknown"
    )


def date_confidence(session, field):
    return (
        session.extra.get("date_provenance", {})
        .get(field, {})
        .get(
            "confidence",
            session.timezone_confidence if getattr(session, field) is not None else "unknown",
        )
    )


def display_session_time(session, field):
    return (
        "ambiguous (timezone not recorded)"
        if date_confidence(session, field) == "ambiguous"
        else display_time(getattr(session, field))
    )


def identity(*parts) -> str:
    return str(uuid.uuid5(NAMESPACE, "\0".join(map(str, parts))))


def location_key(session):
    return identity("location", session.root_id, session.locator)


def safe_text(value: Any) -> str:
    text = str(value if value is not None else "unknown")
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))


def public(value):
    if dataclasses.is_dataclass(value):
        return {f.name: public(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): public(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public(v) for v in value]
    return value


class Failure(Exception):
    def __init__(self, code: str, exit_code: int = 1, *, data=None):
        super().__init__(code)
        self.code, self.exit_code, self.data = code, exit_code, data or {}

    def envelope(self):
        return envelope("error", self.data, error={"code": self.code, "message": self.code})


def envelope(kind, data, *, sources=None, completeness=None, warnings=None, error=None):
    return {
        "schema_version": 1,
        "kind": kind,
        "data": public(data),
        "sources": sources or [],
        "completeness": completeness or {},
        "warnings": warnings or [],
        "error": error,
    }


@dataclass(frozen=True)
class Capability:
    state: str
    reason: str | None = None

    def __post_init__(self):
        if self.state not in ("supported", "unavailable", "unsafe"):
            raise ValueError("invalid capability")


def capabilities():
    return {key: Capability("unavailable", "not_verified") for key in CAPABILITY_NAMES}


@dataclass
class SourceRoot:
    root_id: str
    provider: str
    namespace_id: str
    path: Path
    root_kind: str = "native_home"
    enabled: bool = True
    default_root: bool = False
    reader_profile: str | None = None
    schema_fingerprint: str | None = None
    executable_path: Path | None = None
    executable_version: str | None = None
    resume_context: str | None = None
    health: str = "unknown"
    last_scan_id: str | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.default_root) is not bool:
            raise ValueError("invalid source control flag")
        for value in (self.root_id, self.namespace_id):
            _identifier(value)
        if self.provider not in PROVIDERS:
            raise ValueError("invalid provider")
        _absolute_path(self.path)
        self.path = Path(self.path)
        if self.executable_path is not None:
            _absolute_path(self.executable_path)
            self.executable_path = Path(self.executable_path)

    @classmethod
    def create(cls, provider, path, namespace="default", **kwargs):
        if provider not in PROVIDERS:
            raise ValueError("unknown provider")
        path = Path(path).expanduser().absolute()
        return cls(
            identity("root", provider, namespace, str(path)),
            provider,
            provider + ":" + namespace,
            path,
            **kwargs,
        )


@dataclass
class SessionLocation:
    session_uid: str
    root_id: str
    locator: str
    fingerprints: dict = field(default_factory=dict)
    completeness: str = "complete"
    status: str = "preferred"

    def __post_init__(self):
        _identifier(self.session_uid)
        _identifier(self.root_id)
        _absolute_path(self.locator)
        if self.completeness not in COMPLETENESS or self.status not in (
            "preferred",
            "alias",
            "conflict",
        ):
            raise ValueError("invalid location state")


@dataclass
class Project:
    project_id: str
    cwd: str
    display_name: str
    path_available: bool

    def __post_init__(self):
        _identifier(self.project_id)
        _absolute_path(self.cwd)
        if not isinstance(self.display_name, str) or type(self.path_available) is not bool:
            raise ValueError("invalid project")


@dataclass
class ActivityEvidence:
    session_uid: str
    status: str = "unknown"
    evidence_kind: str = "none"
    observed_at: int = field(default_factory=now_ms)
    pid: int | None = None
    process_start_identity: str | None = None
    resolved_executable: str | None = None
    confidence: str = "unknown"

    def __post_init__(self):
        _identifier(self.session_uid)
        if self.status not in ("active", "inactive", "unknown"):
            raise ValueError("invalid activity state")
        _milliseconds(self.observed_at)
        if self.pid is not None and (type(self.pid) is not int or self.pid <= 0):
            raise ValueError("invalid process identity")
        if self.resolved_executable is not None:
            _absolute_path(self.resolved_executable)


@dataclass
class ScanGeneration:
    scan_id: str
    root_id: str
    state: str = "running"
    started_at: int = field(default_factory=now_ms)
    finished_at: int | None = None
    enumeration: str = "unavailable"
    history: str = "unavailable"
    search: str = "unavailable"
    usage: str = "unavailable"
    source_revision_range: list = field(default_factory=list)
    reader_version: str = "1"
    normalizer_version: str = NORMALIZER_VERSION
    diagnostics: list = field(default_factory=list)

    def __post_init__(self):
        _identifier(self.scan_id)
        _identifier(self.root_id)
        if self.state not in ("running", "complete", "partial", "cancelled", "failed"):
            raise ValueError("invalid scan state")
        if any(
            value not in COMPLETENESS
            for value in (self.enumeration, self.history, self.search, self.usage)
        ):
            raise ValueError("invalid scan completeness")
        _milliseconds(self.started_at)
        _milliseconds(self.finished_at, optional=True)
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("invalid scan time range")
        if not isinstance(self.source_revision_range, list) or not isinstance(
            self.diagnostics, list
        ):
            raise ValueError("invalid scan provenance")


@dataclass
class Session:
    session_uid: str
    display_id: str
    namespace_id: str
    native_id: str | None
    provider: str
    root_id: str
    locator: str
    title: str | None = None
    preview: str | None = None
    cwd: str | None = None
    project_id: str | None = None
    model: str | None = None
    created_at: int | None = None
    last_activity_at: int | None = None
    time_provenance: str = "native"
    timezone_confidence: str = "known"
    hidden: bool = False
    presence: str = "present"
    activity: str = "unknown"
    activity_evidence: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=capabilities)
    current_generation: str | None = None
    fingerprint: dict = field(default_factory=dict)
    profile: str | None = None
    history_state: str = "unavailable"
    search_state: str = "unavailable"
    usage_state: str = "unavailable"
    known_bytes: int | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        for value in (self.session_uid, self.display_id, self.namespace_id, self.root_id):
            _identifier(value)
        if (
            self.provider not in PROVIDERS
            or self.presence
            not in ("present", "source_unavailable", "missing", "trashed", "purged")
            or self.activity not in ("active", "inactive", "unknown")
        ):
            raise ValueError("invalid session state")
        if any(
            value not in COMPLETENESS
            for value in (self.history_state, self.search_state, self.usage_state)
        ):
            raise ValueError("invalid session completeness")
        if type(self.hidden) is not bool:
            raise ValueError("invalid visibility")
        if self.timezone_confidence not in ("known", "unknown", "ambiguous"):
            raise ValueError("invalid timezone confidence")
        if any(
            not isinstance(value, dict)
            for value in (self.extra, self.fingerprint, self.activity_evidence, self.capabilities)
        ):
            raise ValueError("invalid session attributes")
        if set(self.capabilities) != set(CAPABILITY_NAMES) or any(
            not isinstance(value, Capability) for value in self.capabilities.values()
        ):
            raise ValueError("invalid session capabilities")
        _absolute_path(self.locator)
        if self.cwd is not None:
            _absolute_path(self.cwd)
        for key in ("title", "preview", "cwd", "model", "native_id"):
            if getattr(self, key) is not None and not isinstance(getattr(self, key), str):
                raise ValueError("invalid metadata type")
        for value in (self.created_at, self.last_activity_at):
            if value is not None and type(value) is not int:
                raise ValueError("invalid UTC milliseconds")
        counter(self.known_bytes)

    @classmethod
    def build(cls, root, native_id, locator, **kwargs):
        stamp = kwargs.get("fingerprint", {})
        surrogate = (
            "artifact:" + str(stamp["dev"]) + ":" + str(stamp["inode"])
            if "dev" in stamp and "inode" in stamp
            else "artifact:" + str(locator)
        )
        uid = identity(root.namespace_id, native_id if native_id else surrogate)
        cwd = kwargs.get("cwd")
        if cwd:
            kwargs["project_id"] = identity("project", str(Path(cwd).absolute()))
        return cls(
            uid,
            "s-" + uid,
            root.namespace_id,
            native_id,
            root.provider,
            root.root_id,
            str(locator),
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        stored = data.get("capabilities", {})
        if not isinstance(stored, dict):
            raise ValueError("invalid session capabilities")
        data["capabilities"] = {
            k: Capability(**v) if isinstance(v, dict) else v for k, v in stored.items()
        }
        for key in CAPABILITY_NAMES:
            if key not in data["capabilities"]:
                data["capabilities"][key] = Capability("unavailable", "not_verified")
        return cls(**data)


@dataclass
class HistoryEvent:
    event_uid: str
    role: str
    ordinal: int
    text: str | None = None
    timestamp: int | None = None
    native_id: str | None = None
    parent_id: str | None = None
    turn_id: str | None = None
    completeness: str = "complete"
    locator: str | None = None
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.role not in (
            "user",
            "assistant",
            "tool_call",
            "tool_result",
            "system",
            "unsupported",
        ):
            raise ValueError("invalid history role")
        counter(self.ordinal)
        if self.text is not None and not isinstance(self.text, str):
            raise ValueError("invalid history text")


@dataclass
class HistoryResult:
    events: list[HistoryEvent] = field(default_factory=list)
    state: str = "complete"
    reason: str | None = None
    revision: dict = field(default_factory=dict)


@dataclass
class LaunchRequest:
    launch_id: str
    session_uid: str
    source_fingerprint: dict
    history_locator: dict
    executable: str
    argv: list[str]
    cwd: str
    context_overrides: dict
    target: str
    data_dir: str
    owner_uid: int
    source_root: dict = field(default_factory=dict)
    executable_fingerprint: dict = field(default_factory=dict)
    alias_bindings: list[dict] = field(default_factory=list)
    created_at: int = field(default_factory=now_ms)
    expires_at: int = field(default_factory=lambda: now_ms() + 120000)
    state: str = "requested"

    def __post_init__(self):
        if not Path(self.executable).is_absolute() or not Path(self.cwd).is_absolute():
            raise ValueError("absolute launch paths required")
        if (
            self.target not in ("current", "warp")
            or not self.argv
            or self.argv[0] != self.executable
        ):
            raise ValueError("invalid launch vector")
        if any(not isinstance(v, str) or "\0" in v for v in self.argv):
            raise ValueError("invalid launch argument")
        if set(self.context_overrides) - {"CODEX_HOME", "CLAUDE_CONFIG_DIR"}:
            raise ValueError("unapproved launch context")
        if self.state not in (
            "requested",
            "claimed",
            "handoff_attempted",
            "child_exited",
            "exec_failed",
            "expired",
            "delivery_failed",
        ):
            raise ValueError("invalid launch state")


@dataclass
class ManualResumeGuide:
    provider: str
    native_id: str | None
    history_locator: dict
    original_cwd: str | None
    requested_cwd: str | None
    reason: str
    help_argv: list[str]
    options: list[str] = field(default_factory=lambda: ["choose_cwd", "cancel"])
    steps: list[str] = field(
        default_factory=lambda: [
            "Choose the original existing project directory or cancel.",
            "Relocated-workspace binding has not been verified. Consult the native CLI help; history is not moved automatically.",
        ]
    )


@dataclass
class OperationPlan:
    plan_id: str
    action: str
    target_ids: list[str]
    targets: list[dict]
    known_bytes: int
    bytes_complete: bool
    created_at: int
    expires_at: int
    confirmation_token_digest: str
    consumed_at: int | None = None
    operation_id: str | None = None

    def __post_init__(self):
        if self.action not in ("trash", "restore", "purge"):
            raise ValueError("invalid operation action")
        counter(self.known_bytes)


@dataclass
class TrashEntry:
    trash_id: str
    session_uid: str
    operation_id: str
    source_root: dict
    source_profile: str
    owner_uid: int
    artifacts: list[dict]
    manifest_version: int = 1
    state: str = "preview"
    snapshot_verified_at: int | None = None
    conflict_reason: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r"t-[a-f0-9-]{36}", self.trash_id):
            raise ValueError("invalid trash identity")


@dataclass
class OperationItem:
    operation_id: str
    target_id: str
    action: str
    state: str = "preview"
    trash_id: str | None = None
    error: str | None = None
    recovery_options: list[str] = field(default_factory=list)
    cleanup_pending: bool = False
    updated_at: int = field(default_factory=now_ms)

    def __post_init__(self):
        _identifier(self.operation_id)
        _identifier(self.target_id)
        if self.action not in ("trash", "restore", "purge") or self.state not in OPERATION_STATES:
            raise ValueError("invalid operation item")
        _milliseconds(self.updated_at)
        if type(self.cleanup_pending) is not bool:
            raise ValueError("invalid cleanup progress")
        if self.trash_id is not None and not re.fullmatch(r"t-[a-f0-9-]{36}", self.trash_id):
            raise ValueError("invalid trash identity")
        if not isinstance(self.recovery_options, list) or any(
            not isinstance(value, str) for value in self.recovery_options
        ):
            raise ValueError("invalid recovery options")


@dataclass
class CleanupBundle:
    session_uid: str
    profile: str
    root_id: str
    artifacts: list[Path]


TOKEN_CATEGORIES = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
)


@dataclass
class UsageFact:
    fact_uid: str
    provider: str
    identity_scope: str
    native_request_id: str
    owner_native_session_id: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    completeness: str = "complete"
    evidence_revision: dict = field(default_factory=dict)

    def __post_init__(self):
        for category in TOKEN_CATEGORIES:
            counter(getattr(self, category))


@dataclass
class UsageMembership:
    session_uid: str
    fact_uid: str
    evidence: str = "native_history"


@dataclass
class UsageSnapshot:
    session_uid: str
    accounting_scope: str
    epoch: str
    values: dict
    completeness: str = "complete"
    summability: str = "unknown"
    native_revision: dict = field(default_factory=dict)
    covered_fact_ids: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.summability not in ("disjoint", "overlapping", "unknown"):
            raise ValueError("invalid snapshot summability")
        if set(self.values) - set(TOKEN_CATEGORIES):
            raise ValueError("unknown usage category")
        self.values = {key: counter(self.values.get(key)) for key in TOKEN_CATEGORIES}


@dataclass
class ContextMetric:
    session_uid: str
    used_tokens: int | None
    max_tokens: int | None
    kind: str = "context"
    source_profile: str | None = None
    native_revision: dict = field(default_factory=dict)
    observed_at: int = field(default_factory=now_ms)
    completeness: str = "complete"

    def __post_init__(self):
        counter(self.used_tokens)
        counter(self.max_tokens)
        if self.kind != "context":
            raise ValueError("invalid context metric")
        _milliseconds(self.observed_at)
        if self.completeness not in COMPLETENESS:
            raise ValueError("invalid context completeness")


@dataclass
class UsageResult:
    facts: list[UsageFact] = field(default_factory=list)
    snapshots: list[UsageSnapshot] = field(default_factory=list)
    memberships: list[UsageMembership] = field(default_factory=list)
    state: str = "complete"
    reason: str | None = None
    context_metrics: list[ContextMetric] = field(default_factory=list)


def short_handles(sessions, minimum=8):
    ordered = sorted((s.display_id, s.session_uid) for s in sessions)
    result = {}
    for index, (value, uid) in enumerate(ordered):
        shared = 0
        for neighbor in (index - 1, index + 1):
            if 0 <= neighbor < len(ordered):
                count = 0
                for a, b in zip(value, ordered[neighbor][0], strict=False):
                    if a != b:
                        break
                    count += 1
                shared = max(shared, count)
        result[uid] = value[: max(minimum + 2, shared + 1)]
    return result


def display_time(value):
    return (
        dt.datetime.fromtimestamp(value / 1000).astimezone().strftime("%Y-%m-%d %H:%M")
        if value is not None
        else "unknown"
    )
