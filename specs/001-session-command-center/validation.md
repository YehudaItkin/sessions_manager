# Native regression fixes — 2026-11-03

This follow-up addresses the owner's failed Claude deletion, missing Codex sessions,
conflicting shortcuts and missing Grok token values. No personal conversation was
launched, deleted, restored or purged during verification.

## Result and regression evidence

- Codex `token_count.info=null` no longer drops the whole source. Per-session history/
  usage exceptions retain metadata and cached history with explicit partial states;
  transient usage failures are retried. `function_call_output.output` text-block arrays
  are normalized before compression; non-text/image data is omitted explicitly as partial.
  These cases reproduced AttributeError, missing/incorrect states and catalog encode
  failures before the fixes. Corresponding contract/integration tests now pass.
- Claude version detection uses only a bounded, owner/permission-checked `--version` probe,
  cached by executable stat identity. Explicit unsupported versions are not overridden;
  replacement triggers a new probe. Mixed compatible JSONL 2.1.x through 2.1.299 is checked
  by session ID, UUID, role and content shape, with runtime 2.1.299 still required.
  The end-to-end TUI test first reproduced cleanup unavailable, then passed move-to-trash
  and restore after configuration reload without an executable_version setting.
- Closed per-session workflows are included: matching JSON run identity/terminal status,
  ordinary local JS copies, and the native `workflows/scripts/` directory. Local script
  paths are bound to run records without following external scriptPath references.
  Wrong identities, running workflows, unknown layout and unsafe links remain blocked.
  Synthetic trash/restore proves byte preservation, untouched neighbors/external scripts,
  and no JS execution. The original allowlist and flat-directory assumption both failed
  positive workflow fixtures before their corrections.
- Keyboard regressions reproduced missing F5/o/r actions. F5 now refreshes, o opens native
  resume, and r restores only inside Trash. `d` is labeled **Move to trash**; `t` opens
  Trash; Purge remains separate and confirmed. Default cancel/closed-session safeguards
  remain in place.
- Grok native `usage.json.session` totals are now read, with identity checks and root/
  nested incompleteness flags. Turns/model breakdowns are not added twice. The regression
  first showed input_tokens=None instead of the expected synthetic 10. Missing usage.json
  remains not_recorded. Project cwd and stored history location remain independent.

## Checks

- Full suite: **156 passed, 4 skipped**. Three corpus tests and real Warp are opt-in;
  the three corpus tests were run separately and passed. Ruff check/format pass.
- Same seed-1 10,000-session / 1,054,646,020-native-byte corpus: fresh catalog **8.591 s**,
  warm search/navigation **0.823 s**, first PTY TUI frame **1.498 s**; 3 passed.
  OS cache was not flushed; prior native reads/profile runs may warm it. Under competing
  load earlier cold runs exceeded 10 seconds (10.490–13.573 s); these were failures,
  not passing claims. Targets remain 10/2 seconds.
- Profiling led to bounded binary-line UTF-8 reads, sharing decoded Codex projection text
  instead of retaining duplicate raw JSON, read-only SQLite mmap bounded to 1 GiB, and reuse
  of Claude shape validation **only during read-only discovery**. Mutating operations
  always reread and validate source shape, fingerprints, activity and version.
- Wheel/sdist build passes. Locked isolated Python 3.12.12 / SQLite 3.53.4 wheel smoke
  outside the checkout passes: help/version, 40-session refresh/list/show/stats, resume
  dry-run, cleanup preview, hide/unhide. Native fixture hashes remain unchanged.
  Wheel SHA-256: `d22bec27412dd27031685cd5eca88c6d4de47e83e4360b8d8d4998513474c02f`.
- Read-only native verification confirms Codex metadata visible, Claude format eligibility
  including completed workflows, and populated Grok counters where native files exist.
  A real PTY over the cached native catalog displays the overview and exits with code 0.
  These checks do not certify real native resume or destructive native operations.

Compatibility/security sources: [Claude local data](https://code.claude.com/docs/en/claude-directory)
documents that --version/--help do not create global config; [workflow lifecycle](https://code.claude.com/docs/en/workflows#how-a-workflow-runs)
describes session-owned script/result storage and the distinction from external scripts.
Only structural native field/type observations informed synthetic fixtures; no transcript,
ID, private path, native JS, credential or production catalog is committed.

Pre-merge self-review: requirements, privacy, failure recovery, version drift, truthful
unknown/partial values, documentation and acceptance evidence checked. These fixes implement
FR-002/007/009, FR-014–019, FR-020–022 and FR-026; keyboard changes serve FR-001/006/011.
The owner's prior authorization to publish/merge into the primary branch applies; default
branch is main. Real AI resume/Warp and the original owner usability gate remain unperformed.

---

# Implementation validation

**Date:** 2026-11-02. **Branch:** `001-session-command-center`. **Version:** 0.1.0.
Implementation tasks are complete. Automated gates pass; owner usability/native-resume and
actual Warp runtime acceptance remain unperformed. The owner authorized integration into
`main` through PR #2. Pending manual gates are not marked as passed.

## Final automated results

| Gate | Result |
| --- | --- |
| `uv sync --locked --group dev` | Locked environment created successfully |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 120 files formatted |
| `uv run pytest tests -q` | **136 passed, 4 skipped**, 13.74 s |
| Explicit full-corpus performance run | **3 passed**, 11.62 s total |
| `uv build` | Wheel and sdist built successfully |
| Isolated wheel install, Python 3.12.12 / SQLite 3.53.4 | PASS, outside repository cwd |
| Document links, Git privacy/whitespace review | PASS; see scope below |

The four default skips are three explicit-corpus performance tests and the opt-in Warp
runtime test. Performance was run separately with `--corpus`; Warp was not run.
The main test environment is uv-managed **CPython 3.14.2 / SQLite 3.50.4**, not the shell's
Python 3.14.8. Dependencies come from `uv.lock`.

## SC-002 performance

Target machine: **Apple M3 Pro, Mac15,6, 11 logical cores, 18 GiB RAM, macOS 27.0.1**.
Corpus seed 1: **10,000 sessions**, 2,500 per provider. Requested history bytes:
1,000,000,000. Actual native artifact bytes: **1,054,646,020**, below 1 GiB
(1,073,741,824). Generator emits IDs, native bytes, provider counts and expected metrics.
Full corpus has 17,500 normalized messages and 50,000 known Claude tokens; other usage
coverage is deliberately explicit and Grok snapshots are not blindly summed.

Reproduce from the repository root:

```sh
perf_root=$(mktemp -d /private/tmp/sessions-manager-perf.XXXXXX)
uv run python -m tests.support.make_corpus --output "$perf_root" --sessions 10000 --history-bytes 1000000000
uv run pytest tests/performance --corpus "$perf_root" -q -s
```

| Measurement | Final result | Target |
| --- | --- | --- |
| Fresh manager catalog: complete discovery + history/search readiness + close | **9.072 s** | ≤10 s |
| Three new processes: literal search, history page, short literal query | **0.763 s** | ≤2 s |
| New process + real PTY: first meaningful TUI frame | **1.408 s** | ≤2 s |

Cache conditions: each cold-manager test uses a new private data-dir and empty catalog.
Native files are unchanged synthetic fixtures; OS file cache was **not flushed**, and
prior profiling/reads may warm it. Warm tests use the completed catalog in separate processes.
No provider was omitted or query limited to return a falsely complete search.
Final published root `as_of` range: **2026-11-02 17:03:41.880–17:03:45.949 UTC**.
These are measurements on this machine and cache condition, not a universal latency guarantee.

Earlier failing measurements were retained as development evidence, not passing claims:
35.614 s cold / 25.424 s warm on the initial 800 MB requested-history corpus;
11.647 s cold near 1 GiB before final optimization; 28.845 s after adding cleanup capability
probes exposed repeated Grok sibling enumeration. Targets stayed 10/2 seconds.
Optimizations: whole-message compressed storage; deduplicated overlapping candidate windows
preserving every trigram plus exact full-field verification; metadata separate from history FTS;
fixed read-only SQLite mmap; up to four spawned root readers and four bounded file-open
threads per independent file reader; ready roots published by the sole writer while remaining
readers finish; no decode of compressed bodies until display. Shared Grok topology checks are
cached only within a discovery scan; cleanup commit always probes again.

## Packaging and documented smoke

Built `sessions_manager-0.1.0-py3-none-any.whl` and `sessions_manager-0.1.0.tar.gz`.
Wheel SHA-256: `3a2b27668e022e6cd8b60f4eb305fae26f3f0049daca0a7483e7cb5d041a06b1`.
An independent temporary Python 3.12.12 venv received dependencies exported with
`uv export --frozen --no-dev --no-emit-project`, then the wheel with `--no-deps`.
Import location was verified under that venv's site-packages; cwd was outside the checkout
and PYTHONPATH was removed. No global install or HOME replacement occurred.

The documented `python -m tests.support.make_corpus` generated 40 synthetic sessions.
Installed console checks passed: help/version, refresh, JSON list/show, source-group stats,
resume dry-run, cleanup preview, hide/unhide. Expected **40 sessions, 70 messages, 200 known
tokens with incomplete total coverage** matched. Every native fixture file SHA-256 remained
unchanged. Wheel excludes tests/runtime data; sdist contains no catalog or credentials.
Actual source mutations are covered separately by synthetic cleanup acceptance/fault tests.

## TDD evidence

Tests were written/run before the corresponding implementation. Early expected missing
modules/models were followed by observable behavior failures and passing phase checkpoints:
foundations 17 tests; overview 27; history/search 47; resume 61; statistics 104; final 136.

| Increment / reproduced RED | Subsequent GREEN coverage |
| --- | --- |
| Missing foundation models/SQLite boundary and catalog | Owner-only modes, real WAL visibility without changes, unsafe sidecar/schema refusal, parameter binding, atomic rollback |
| Metadata/discovery/overview readers absent | Four synthetic native stores, stable separate IDs, full-root refresh beyond display filters, non-TTY routing |
| History/search models/readers absent; content/pagination assertions failed | Literal Unicode/short/operator-looking queries, long history, bounded Cursor graph, terminal-control sanitization |
| Unicode normalizer change returned zero matches while claiming complete | Stale index detection and rebuild before complete CLI search |
| Launch service/UI/CLI missing; concurrent ticket claim produced two winners | Exact argv/cwd, foreground harmless child, source/executable revalidation, single conditional claim, suspend/return |
| Cleanup service/models/UI missing; live-handle and interrupted-operation assertions failed | Copy/hash/fsync/rename/journal faults, restore conflict/no overwrite, exact-operation retry and mixed receipts |
| Usage models/readers missing; duplicate/snapshot/coverage expectations failed | Unique fact union, ownership separate from container, monotonic Claude usage, unknown lifetime Cursor values |
| Codex reset/mixed legacy receipt streams claimed complete | Partial lifetime and preserved non-summable scopes |
| Codex realtime item missing; changed projection claimed complete | Realtime normalization/dedup and main/WAL/rollout revision checks |
| Details lacked metrics; filtered stats claimed complete over an incomplete search | CLI/TUI usage details and candidate-scope completeness/partial exit |
| TUI lacked sort/group controls; cleanup capability stayed not_verified | Filter sort, source/project/day statistics, proven-profile capability/reason |
| Performance exceeded fixed cold/warm limits | Final full-corpus three-test run above |

Relevant regressions were rerun after edits; final Ruff and the full functional suite pass.
No deliberate breakage was introduced to manufacture a RED for already-correct safety cases.

## Requirement traceability

Paths in this table are relative to `tests/`.

| Requirements | Observable evidence |
| --- | --- |
| FR-001, FR-003 | `contract/test_overview_cli.py`, `acceptance/test_overview.py`: no-arg routing, named/full IDs, stable selection |
| FR-002, FR-004 | Four `contract/test_*_metadata.py`, `integration/test_catalog.py`, `integration/test_discovery.py`: known/unknown stores, dedup, aliases/conflicts |
| FR-005, FR-006 | `unit/test_search.py`, `integration/test_search_index.py`, overview/history command and acceptance tests: sort, simultaneous filters, dates, literal content, refresh scope |
| FR-007 | Four history contracts, `contract/test_history_commands.py`, `acceptance/test_history.py`: normalized order, context membership, details/usage, pages |
| FR-008, FR-009 | `unit/test_activity.py`, source-profile contracts, discovery/history commands: PID birth/executable proof, independent capability reasons, partial source isolation |
| FR-010–FR-012 | `contract/test_resume_commands.py`, `acceptance/test_resume.py`, launch ticket/warp tests: exact selection, cwd binding, refusal + manual guide, harmless handoff |
| FR-013 | `integration/test_hide.py`, cleanup/overview acceptance: persistent manager-only batch hide/unhide |
| FR-014–FR-019 | Cleanup contracts, `integration/test_fsops.py`, `integration/test_cleanup_recovery.py`, `acceptance/test_cleanup.py`: preview/confirmation, backup, activity guard, no-replace, crash/retry, restore/purge |
| FR-020–FR-023 | Four usage contracts, `integration/test_usage_catalog.py`, `unit/test_statistics.py`, stats commands/acceptance: categories, lifetime selection, union/coverage, unknown ≠ zero |
| FR-024, FR-025 | Autouse network block; native SQLite/config/fsops tests; fixture hashes and installed smoke: local reads, unchanged native bytes, strict modes, safe display/argv/errors |
| FR-026 | Discovery/search/command regressions: last successful as_of retained, stale rebuild, incomplete search exit 3, selected-provider health |
| FR-027 | TDD evidence above; synthetic fixtures with expected IDs/metrics and boundary/acceptance tests |

| Success criterion | Status and boundary |
| --- | --- |
| SC-001 | PASS for supported synthetic profiles; exact expected identities/counts/dates, unknowns explicit |
| SC-002 | PASS for the measured full corpus and cache conditions above |
| SC-003 | **NOT RUN**: owner must perform 10 timed find-and-understand tasks; no usability claim |
| SC-004 | Harmless fixtures PASS; **real native conversations and actual Warp NOT RUN**, so native acceptance remains open |
| SC-005 | PASS on controlled usage/overlap/unknown fixtures; unavailable metrics remain unknown |
| SC-006 | PASS on synthetic cleanup/hide/cancel/crash/retry cases; no personal native mutation performed |
| SC-007 | PASS on synthetic file/hash/SQLite/WAL and installed smoke boundaries |
| SC-008 | PASS on controlled source failure, partial query and capability/error cases |

## Privacy, recovery and manual review

All automated inputs are generated synthetic stores with explicit replacement roots. Tests
block network, use harmless executables, do not change HOME, and do not launch AI providers.
Native SQLite uses mode=ro, query_only, trusted_schema off, ordinary whitelisted tables and
an authorizer; views/virtual tables/ATTACH/DDL/DML/repair and missing WAL sidecars are refused.
Sensitive native properties are excluded from manager records; errors omit exception content.
Manager data-dir/source overlap, foreign/future own catalog schemas and executable replacement
are rejected. Runtime directories/files use 0700/0600. Cache content is local private data.

Cleanup fault points include before/after copy, hash/fsync, backup verification, before/after
rename, journal update and final verification, plus interrupted restore. Live `lsof` PID output
blocks mutation even if lsof returns 1 for some other selected file. MacOS no-replace rename
is exercised on synthetic files/directories. Purge removes only exact manager-owned entries
and logical cached transcript, without a forensic secure-erase claim.

Git review includes source/docs/synthetic seeds/lock only, with no generated corpora, native
histories, catalogs, credentials, wheel or venv. Secret-pattern and personal absolute-path scans
found no matches. Checklist requirements.md remains unchanged, all 16 items checked.
Pre-merge agent self-review (2026-11-02): checked constitutional compliance, requirement
traceability, TDD/acceptance evidence, private-data boundaries, compatibility limits and
user documentation against this implementation. The recorded automated gates pass; the
manual gates below remain open and are not represented as passed. The owner explicitly
requested integration into the primary branch. GitHub reports PR #2 mergeable with no
hosted status checks registered. This records the review before the authorized merge;
it does not certify real native resume or expand disabled capabilities.

Unperformed gates: `pytest tests/acceptance/test_warp_runtime.py --run-warp`, owner SC-003,
and consciously selected disposable native conversations in current terminal and Warp per
provider. Delivered/claimed/child-exited never means conversation_loaded. All relocated-cwd
automatic resume remains unavailable until its own native binding gate. Codex cleanup is
intentionally unavailable; custom Grok/Cursor homes remain view-only; Cursor lifetime/context
counters without a proved mapping remain unknown. See quickstart and source/launch contracts.

`.specify/extensions.yml` is absent: no after_implement hooks are registered.
