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

## Native compatibility follow-up — 2026-11-03 (T109–T116)

This section supersedes earlier pending/NOT RUN statements only for the gates explicitly
listed here. No personal native conversation was resumed, trashed, archived or deleted.

- `uv run pytest -q`: **176 passed, 4 skipped**, 16.00 s. Skips are three opt-in corpus
  tests and the opt-in actual Warp runtime test, which was run separately as recorded below.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`, `git diff --check`:
  PASS, 96 Python files formatted. No new package dependency.
- Same SC-002 seed-1 mixed 10,000-session / 1,054,646,020-byte corpus: **3 passed**,
  cold discovery **8.494 s** (<=10), warm search/navigation **0.833 s** and first meaningful
  PTY TUI frame **1.479 s** (<=2). macOS 27.0.1 / M3 Pro / 18 GiB; OS cache not flushed.
  Corpus generation excluded; targets unchanged; no unrelated verification workload ran
  concurrently with this measurement.
- `uv build`: PASS. Fresh Python **3.12.12 / SQLite 3.53.4** venv outside checkout, locked
  runtime dependencies, installed wheel: help/version/refresh/list/show/stats/dry-run
  resume/cleanup preview/hide/unhide PASS. **40 sessions, 70 messages, 200 known tokens**;
  all native synthetic file SHA-256 unchanged. Wheel SHA-256:
  `fd9f125100f3e9dff53f0769a8ee5004cac094052f0941d01fbfeb33b1079ab3`.
- `uv run python -m tests.support.verify_native_codex --executable /absolute/codex`:
  **PASS** for installed 0.166.0, using a new private offline native home. Real app-server
  restart retained synthetic context; archive/unarchive retained selected ID and unrelated
  neighbor. Actual cold CLI PTY resume after original project rename loaded the recorded
  context, persisted the same ID with new cwd and created **zero new sessions**. Receipt
  booleans all true. HOME unchanged; no production credentials copied; only closed-loopback
  synthetic provider used. This gate does not certify Codex cleanup/cascade boundaries.
- Grok/Cursor detected-version synthetic trash/restore roundtrip: PASS after catalog close
  and a fresh service; selected bytes restored exactly, neighbor bytes unchanged. Open
  handles, unknown dependencies, unsupported versions and source drift remain guarded.
- Read-only native scan: metadata complete for **199 Codex, 26 Claude, 117 Grok, 5 Cursor**.
  Cursor recovered all three chats lacking sidecars; cwd known for five, history one complete
  / four partial, cleanup eligible for five. Codex metadata-only stale entries remain visible:
  final resume capability **182 supported / 17 history_not_recorded**. Claude cleanup eligible
  for 26. Grok cleanup remains **117 shared_dependency_unverified**. Counts are a snapshot,
  not fixed fixtures; private IDs, contents and paths were not copied to this repository.

TDD evidence observed before fixes:

| Expected RED | GREEN behavior |
| --- | --- |
| Three missing-sidecar/binary-hash Cursor regressions failed | Native metadata and verified neighbor cwd retained; binary hashes resolve |
| Unknown first turn hid later history; shell turn was partial | Later messages retained; shell command/output displayed without execution |
| 32-character legacy text key became a false binary reference | Exact existing legacy blob remains readable |
| Three automatic provider-version cases returned None | Strict bounded version-only Grok/Cursor/Codex detection passes |
| Paginated Codex without rollout unavailable | Known 0.166 + persisted thread items enables exact resume |
| Metadata-only paginated row falsely resumable | history_not_recorded without a child launch |
| Relocated Codex request rejected | Verified paginated profile retains original locator/ID and new cwd |
| Missing human explanations and CLI showed raw code | Human recovery text; JSON codes/payloads unchanged |
| Warp delivered response lacked actionable fallback | Explicit Current terminal guidance, with no loaded claim |

Actual Warp gate: `uv run pytest tests/acceptance/test_warp_runtime.py --run-warp -q`
**FAIL**, on installed **0.2026.10.21.08.25.02**. URI delivery succeeded but ticket stayed
requested; harmless fixture child did not ack within 20 seconds. Launcher import from /
passed and TOML matches current documentation. Native startup cause remains unverified.
Computer Use returned “not allowed ... for safety reasons” for Warp; no alternate UI
control was attempted. Expired manager-owned launch artifacts were cleaned using normal
expiry handling. **T113 remains open**, with Current terminal as the documented alternative.

Native limits explicitly retained: **T117** covers safe Grok shared-index/legacy DB scope
and recovery; **T118** requires bounded Codex native cascade/revision support. Existing
threadId-only archive/delete APIs do not provide a confirmed descendant set or conditional
revision. A successful isolated archive roundtrip does not waive that requirement. No
file-only ghost deletion, shared DB DML, remote Grok deletion or whole-DB rollback was added.
Missing native token/history data remains unknown, with a human explanation.

Maintainer self-review: constitutional traceability/TDD, source identity/cwd preservation,
read-only native boundaries, trusted executable checks, cleanup guards, JSON compatibility,
privacy and documentation checked. The changed-file review found no credentials, personal
native IDs/transcripts/paths, production catalogs or generated corpora. Sole-maintainer
self-review is recorded; requested publication is via branch/PR into main, with no bypass
of hosted required checks. Warp's failing opt-in gate is explicitly excluded from passing
acceptance and remains tracked, rather than being relabeled as a successful launch.

## Filtering/sorting follow-up — 2026-11-04 (T119–T125)

- `uv run pytest -q --tb=short`: **212 passed, 6 skipped**, 22.49 s. Skips are the five
  explicit-corpus performance gates and the existing opt-in Warp gate. No real native
  conversation/lifecycle operation is needed for this feature.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`, `git diff --check`:
  PASS; **99 Python files** formatted. Product code and all final regressions were included in the final functional run.
- Same mixed, seed-1 **10,000-session / 1,054,646,020-byte** synthetic corpus,
  `uv run pytest tests/performance --corpus PRIVATE_CORPUS -q -s --tb=short`:
  **5 passed**, 14.71 s. After the final table-layout fix, both affected TUI gates
  were rerun: **2 passed**, 5.13 s. Latest results: cold discovery **8.257 s** (<=10), warm search/navigation
  **0.932 s**, meaningful PTY TUI frame **1.697 s**, combined multi-source/project/model/
  activity/date filtering + sorting + pagination in a new process **0.288 s**, real Pilot
  header-click resort of 10,000 rows **1.495 s** (all warm targets <=2).
  Unknown-last and ID selection preservation remain asserted. Same machine as the
  preceding measurement; OS cache not flushed; no unrelated validation ran concurrently
  with the corpus measurement. Corpus generation is excluded and targets unchanged.
- `uv build`: PASS. Fresh outside-checkout installed wheel, **Python 3.12.12 / SQLite
  3.54.1**, locked runtime dependencies: help/version/refresh/list/show/stats/resume dry-run/
  cleanup preview/hide/unhide smoke PASS. New multi-filter/sort flags, model/activity stats,
  descending native-ID order and filtered refresh also PASS. Installed Python 3.12 TUI
  at **80x24** also passes visible toolbar, actual button click, model filtering, direction,
  header toggle and selected-ID preservation checks. **40 sessions, 70 messages,
  200 known tokens**, all synthetic native file hashes unchanged. Wheel SHA-256:
  `f7462c3447db3c831fbe28640be99d942b45e30a328b15e0e9d3ace238305920`.

Observed RED → GREEN evidence:

| Initial failing behavior | Verified result |
| --- | --- |
| 20 QuerySpec cases failed: new selectors/direction absent | Combined filters, ten sort fields, direction/defaults, stable ties, unknown-last and validation pass |
| Seven CLI cases failed: flags unsupported | list/refresh/stats share selectors; whole-selection sorting precedes pagination; invalid activity rejects before data-dir creation |
| Claude model metadata was None despite recorded assistant model | Last recorded nonempty assistant model retained; user metadata does not override it |
| Three Pilot cases failed: no visible button/multi-source control/header sorting | Visible controls/summary, multi-source Apply/reopen, direction/reset, actual header toggles and stable selected ID pass |
| A 40-row table at 80x24 scrolled the toolbar off screen (also reproduced in installed wheel) | Table height fills remaining space and scrolls internally; toolbar remains clickable |
| Enter in a filter field changed the main query | Only the main query Input submission changes search; filter draft remains editable |
| Invalid-date messages gave generic retry advice | Format/range messages explain how to correct the field |

Additional Pilot acceptance includes **80x24** keyboard Space source toggling without
changing the main batch, Escape/cancel behavior, invalid empty-source/date drafts staying
editable, reset defaults, current-filter retention across refresh and pruning invisible
batch targets before actions. Model/project/activity/date/query filters never narrow
source enumeration; a changed excluded-model neighbor is still reconciled, with source
bytes unchanged. Existing search completeness and lifecycle tests pass.

Compatibility: recent/oldest and list defaults remain; JSON envelope/data schemas and
stored session schema are unchanged. New filter/sort options are additive. UI settings
are per-run and survive refresh, without introducing a preferences store. The new Claude
metadata field uses already-read known assistant records; existing cached sessions need
F5/refresh to populate it. Unknown model/activity/size is retained; no metrics are invented.
Independent native capability tasks T113/T117/T118 retain their previous status.

Sole-maintainer self-review recorded: FR-006/spec/plan/task traceability, TDD evidence,
read-only boundaries, literal query/text handling, source selection vs refresh scope,
stable row identities, batch action scope, nullable data, backwards compatibility,
package behavior and documentation checked. No dependency, migration, shared native DB
write, live process control or external AI call was introduced. Only synthetic stores
were used for acceptance and packaging; no personal histories/credentials/catalogs or
benchmark corpora are included in the change. Publication follows the authorized GitHub
branch/PR/merge workflow with no bypass of required checks.


## Convergence implementation — 2026-11-05

- T126: three unsafe Warp directory/ancestor/symlink regressions failed before the fix; 10 Warp/ticket checks passed after it. Launcher paths are checked before creating tickets/configs; unsafe existing directories are rejected without chmod. Root-owned sticky ancestors are accepted because they protect owned children.
- T127: late companion and stale purge confirmation regressions failed before the fix; all 35 cleanup/profile/recovery checks passed after it. Full bundle revalidation precedes the first native rename; resumed operations reconcile their own journal.
- T128: shared-event revision regression failed (neighbor displayed BETA while search matched ALPHA); 21 history/search/catalog/discovery checks passed after content-revision storage and conflict marking. Additive logical_uid migration preserves old catalogs; normalizer 3 forces source reindexing of old caches.
- T129: Claude malformed preview and Grok info-array regressions failed by discarding healthy neighbors; 21 discovery/source checks passed after per-record isolation and optional-preview validation.
- T130/T113: native Warp runtime remains BLOCKED on 2026-11-05. Computer Use getApp("Warp") returned: Computer Use is not allowed to use the app dev.warp.Warp-Stable for safety reasons. No alternate shell/UI path was attempted. No runtime passing claim; URI delivery still does not confirm conversation loading. Independent code fixes continue.
- T131: all eight missing/non-executable provider cases and both nonzero TUI child-exit cases failed before the fix; 24 resume/model checks passed afterward. Metadata remains readable without a CLI; foreground returns include exit/interruption messages.
- T132: original-text context API regressions (Unicode STRASSE/ß, literal %/_, late history-only match) failed before implementation; 20 history/search/statistics and 14 CLI/TUI boundary checks passed. Snippets are bounded and sanitized; persistent previews remain unchanged. Shared revision message counts use logical native identities, not content-revision rows.
- T133: cross-filter/page handle collision regression failed before implementation; 14 CLI/TUI checks passed after global handle selection and action/unknown output. JSON retains full IDs and adds per-page handles/matches.
- T134: stats selection/range and TUI scope regressions failed before implementation; all 9 relevant stats/search checks passed. All/Visible/Hidden selection is explicit and persists between statistics screens; default all still includes hidden and excludes trash. Lifetime-period semantics are unchanged.
- T135: both history-before-metadata publication and blocked-reader TUI regressions failed before implementation; 26 discovery/catalog/overview/statistics checks passed. Bounded workers publish metadata then completed roots through one writer; generation payloads record actual reader start/end, completeness and revision ranges.
- T136: persisted append cursor and purge-retention regressions failed before implementation. All 42 cursor/discovery/usage/history/recovery checks passed, including replacement, truncation, schema drift, incomplete tail completion, neighboring cache retention and secret-property exclusion. Prefix bytes are read for SHA-256 verification; only the new complete tail is JSON-decoded. This deliberately does not promise tail-only disk I/O. Native files are never written.
- T137: 13 typed-boundary regressions plus invalid persisted catalog payload failed before implementation; 41 model/catalog/discovery/statistics checks passed. Invalid records produce a content-free catalog_record_invalid error without silently rewriting or clearing the catalog.
- T138: four context-only scalar/absence regressions failed before implementation. 14 Cursor/history/usage/UI checks and 9 focused context checks passed, including malformed wire and human CLI output. Installed descriptors establish the mapping; no vendor code execution, secret extraction or lifetime estimate.
- T139/T117: feasibility completed with a documented unavailable shared-index profile. Two home/index-sidecar guard regressions failed before the fix; all 39 Grok/Cursor/cleanup-recovery checks passed after it. Supported standalone Grok files still support verified trash, retry and restore. Shared native stores and remote delete were not mutated.
- Self-review follow-up: a new worker-transport regression reproduced shared-body mixing across IPC; buffers are now keyed by session + logical event. All 19 relevant history/discovery/CLI checks passed after the fix.
- Recovery follow-up: corrupt checkpoint, symlink-target invalidation and cancelled-generation regressions failed before correction; all 41 relevant cursor/discovery/history/resume checks passed afterward.
- SC-002 regression investigation: initial cold refresh 90.667 s FAIL; EXPLAIN showed membership scans, fixed by event membership index. Next cold 13.402 s FAIL; cProfile identified quadratic cursor ownership lookup (17.738 s of profiled publish time), replaced with locator lookup. Subsequent cold 6.956 s PASS; warm search/navigation 1.295 s, TUI first frame 1.474 s, combined filters/sort 0.526 s, TUI sort 1.532 s — all PASS without changing thresholds. Final rerun follows below.
- Corpus: seed 1, 10,000 mixed sessions, requested 1,073,741,824 history bytes, actual native bytes 1,130,797,988; generated exclusively by tests.support.make_corpus. macOS 27.0.1 arm64, CPython 3.14.2; cold uses a fresh private catalog, warm uses that completed catalog in new processes. Native reads are synthetic-only; generation reader as_of/revisions are recorded in the benchmark catalog.
- Packaging: uv build produced wheel + sdist; uv sync --locked --no-dev in a fresh temporary environment, wheel reinstall, sessions --help/--version and synthetic complete-search smoke all passed. No global environment or HOME was changed.
- Final functional checks: 284 passed, 6 skipped (opt-in native Warp and performance without corpus); Ruff check, formatting of 101 Python files and git diff --check pass. Final wheel/sdist rebuilt and isolated wheel reinstall/console entry passed.
- Performance follow-up: a concurrent functional/performance run recorded cold 12.629 s FAIL (reader times roughly doubled under concurrent load); the isolated run recorded cold 7.046 s PASS but TUI sort 2.227 s FAIL. Removed duplicate session deserialization in TUI refresh and redundant temporary capability construction during model validation; 34 model/catalog/overview/filter checks and the full 284-test suite passed. Thresholds and test corpus remain unchanged.
- Constitution/self-review: requirements and source refs remain in Phase 9; all changed behavior began with observed failing synthetic regressions. Added manager state is bounded to existing source/catalog responsibilities, with its simpler alternative/tradeoffs documented in plan.md. Parser cache is private, whitelisted and session-retained; cleanup/race/retry/neighbor guards are tested. All migrations are manager-only/additive; docs/contracts reflect actual behavior and external limitations. GitHub delivery uses an isolated branch and PR. No personal session deletion, remote native deletion, secret copying, shared native DB DML or global environment changes.
- Hardware: Apple M3 Pro, 19,327,352,832 bytes RAM (18 GiB). Installed Codex remains 0.166.0; T118 still requires a native revision/descendant/recovery API and is not bypassed.
- Final isolated SC-002: all 5 performance checks PASS. Cold refresh 8.060 s (<=10); warm search/navigation 1.192 s, first TUI frame 1.223 s, combined filter/sort 0.502 s, TUI sort 1.340 s (each <=2). No simultaneous functional test workload.
- Final synthetic reader provenance (UTC epoch milliseconds): started_at minimum 1793872314152, finished_at maximum 1793872318728; final root as_of {"claude": 1793872316241, "codex": 1793872317459, "cursor": 1793872318728, "grok": 1793872318227}.
- Outcome: Phase 9 T126–T129/T131–T139 completed (13/14). T130 and its original T113 runtime gate remain externally blocked; T118 remains conditional on native API support. Checklists were read-only (16/16 PASS); no .specify/extensions.yml exists, so pre/post implementation hooks were skipped.


## Phase 10 implementation — 2026-11-05

- T140: six writable-parent/ancestor-link/platform-binding/dot-dot regressions failed before implementation. Descriptor-relative trusted-directory traversal now validates ownership/modes and binds root-owned platform aliases; native containment rejects dot-dot before filesystem changes. All 26 config/filesystem/cleanup/catalog/Warp checks passed, including parent substitution and root-owned sticky ancestors. Existing directories are never chmodded.

T141: observed failing missing-root (four providers), denied nested enumeration, deeply nested JSONL and worker-failure regressions before implementation. Explicit enumeration outcomes, bounded checkpoint projection and per-worker failure isolation now preserve healthy sessions and propagate KeyboardInterrupt. Targeted discovery/parser/provider/overview suite: **43 passed**.

T142: eight alias-generation regressions observed failing before implementation. Per-location native evidence and shared refresh-cycle IDs now block resume until known copies agree, preserve available history as partial and retain full snapshots against late metadata. Empty peer scans release guards; failed/cancelled peers do not block unrelated sessions. Launch consults the read-only current catalog guard and revalidates every agreed native location. Cleanup for multiple locations remains unavailable. Alias/launch/Warp protocol checks: **43 passed**; discovery/history/cleanup subset: **34 passed**.

T143: three lifecycle regressions failed before implementation: old restored-entry purge destroyed a newer trash cache, and verified native reappearance stayed hidden behind trashed/purged state. Current trash ownership is now explicit in the manager catalog (legacy ownership binds only when unambiguous). Full native history evidence revives stable IDs/hidden state; metadata/header-only and Codex projection-only discoveries do not. Cleanup/recovery/alias/catalog suite: **34 passed**; additional header/projection exclusions pass.

T144 remains **BLOCKED externally** by the previously recorded Computer Use denial for dev.warp.Warp-Stable. No alternate access, personal conversation or native runtime launch was attempted. T113/T130 remain unchecked and T118's native API gate is unchanged.

T145: four terminal-purge regressions failed before implementation (error before final removal, error after removal, partial manifest removal and new contents after a crash). A committed purged receipt is retained; cleanup_pending separately reports final directory/fsync work and permits same-operation retry after restart. Only the verified original manifest or empty directory may be removed; new contents are refused. Recovery/cleanup suite: **31 passed**. An additional CLI regression reproduced exit 0 for pending cleanup; commit/retry now return a nonzero exit with the durable purged state.

- Phase 10 self-review follow-ups: graph-only alias conflict, filesystem root as private data-dir, and dangling manager-directory link regressions each failed before correction. Graph/content digest version 2 now includes parent/turn context; final trusted leaf checks also cover `/`; read-only launch guards reject dangling manager aliases. All 24 relevant config/alias checks passed.
- IPC alias follow-up: history text displayed correctly but worker-prepared search chunks were lost during location reconciliation. A new regression failed before preserving the selected copy's prepared chunks, while actual conflicting copies remain unindexed.
- SC-002 isolated run: **5 passed**. Cold 6.421 s (<=10); warm search/navigation 1.262 s, first TUI frame 1.187 s, combined filter/sort 0.493 s, TUI sort 1.269 s (each <=2). Seed 1; 10,000 mixed sessions; requested 1,073,741,824 bytes; actual native bytes 1,130,797,988. No simultaneous test/build/smoke workload. The subsequent IPC fix is restricted to multi-root alias publication, a branch absent from this default one-root-per-provider corpus. Thresholds unchanged.
- Packaging: wheel and sdist build passed; isolated outside-checkout wheel installation with locked runtime dependencies on Python 3.12.12 / SQLite 3.54.1 passed help/version/refresh/list/show/stats/resume dry-run/hide/unhide and two trash/restore/purge lifecycle cycles. All original file hashes of 40 synthetic sessions matched after recovery.

- Pre-schema-follow-up functional suite: **323 passed, 6 skipped** (5 performance opt-ins without corpus + 1 blocked native Warp opt-in). Ruff check, format check of 102 Python files and git diff --check PASS. Pre-schema-follow-up wheel rebuild/reinstall follows the alias IPC fix; SHA-256 `eb82028a33b76e3e03912105d70fbea2639e935ee9d16049cd63be78c9c7d1bb`.
- Benchmark environment: Apple M3 Pro / 18 GiB, macOS 27.0.1 arm64, CPython 3.14.2, SQLite 3.50.4. Reader start minimum 1793879083775; finish maximum 1793879087876; root as_of {codex:1793879086091, grok:1793879087284, claude:1793879085664, cursor:1793879087876}. Corpus generation is excluded; OS caches are not flushed.
- Sole-maintainer self-review recorded: Phase 10 traces to F1–F6/FR-004/009/018/019/025/026; observed RED-to-GREEN evidence, native read-only boundaries, lifecycle ownership, alias guards across workers, same-operation recovery, additive manager migrations, package compatibility, docs and constitution reviewed. No dependency, personal source mutation, credential access, source DB DML or new native deletion capability. Five code tasks T140–T143/T145 complete; T144 remains externally blocked, with T113/T130 and conditional T118 unchanged. Requirements checklist stays read-only at 16/16 PASS; .specify/extensions.yml is absent, so no pre/post hooks apply.

- Schema compatibility follow-up: a v1 upgrade regression failed before assigning schema v2. Optional location/owner columns and the version marker now commit together; legacy records/hidden state are retained, while older binaries reject the upgraded catalog safely before writes. README/data-model document automatic v1 upgrade and the downgrade boundary.

- Final post-migration validation: **324 passed, 6 skipped**. Catalog/recovery/alias subset **43 passed**. Final wheel and sdist rebuilt, Python 3.12 installed-wheel smoke repeated successfully after schema v2; wheel SHA-256 `34aa9731f1f141ae1b0726179c9ddd7123d80069289dec3973b14780c3287b11`.
- Post-migration overlap audit: a passing 7.452 s cold / 1.173–1.447 s warm run overlapped the last functional suite and is excluded from release timing evidence.
- Final isolated SC-002 on schema v2: **5 passed**. Cold **6.830 s**; warm search/navigation **1.227 s**, first TUI frame **1.263 s**, combined filter/sort **0.494 s**, TUI sort **1.288 s**. No concurrent validation/build workload. Same 10,000-session/1 GiB requested corpus, actual native bytes and unchanged <=10/<=2 thresholds. Provenance: `{"maximum_finish": 1793879447435, "minimum_start": 1793879442975, "root_as_of": {"claude": 1793879445083, "codex": 1793879445438, "cursor": 1793879447435, "grok": 1793879446542}, "schema": 2}`.


## Phase 11 native archive — 2026-11-05

- T146: native 0.166.0 fixture gate PASS (archive and unarchive cascades; parent/two descendants including pre-archived child/neighbor, restart, original flags, IDs/history preserved). Initial parent-only unarchive probe failed the expected original-flags assertion; reconciliation must account for both cascades. Test-only graph seeding and offline isolation are explicit in the reproducible support module. Personal stores were not opened.
- Requirements checklist is read-only: 16/16 PASS; extension hooks file absent.

- T147: archived metadata/default active catalog regressions observed RED; records/IDs/hidden state retained, active view/stats exclude native archives. Invalid archived flags isolate records. A closed-WAL discovery regression reproduced unavailable sources; explicit verified read-only snapshots now avoid sidecar writes and still read live WAL correctly.
- T148: nine initial coordinator regressions failed before implementation. Exact graph, closed assertion, known activity/handles/aliases, lost reply, partial cascade, crash intent, same-operation retry, restart and pre-archived child flags now pass. Follow-up regressions reproduced config-version spoofing, removed-source journal inspection, missing out-of-home rollout references, recursive deep-graph failure and malformed stored flags; corrected before enabling the profile.
- Recovery follow-up: startup failed_no_change permits new preview; uncertain Unarchive restores prior child flags on retry; external archives preserve descendants' existing states. Pending-operation resume bypass and refresh-during-confirm regressions failed before fixes.
- T149: CLI unsupported commands and TUI showing archived rows reproduced RED before adding preview/confirm/list/retry commands, visible controls and separate archive modal at 80x24. Cancellation leaves native data unchanged.
- Cache follow-up: native history changes were incorrectly hidden behind updated cached fingerprints, and a late reader undid archived flags. Both regressions failed before cache invalidation and SessionLocation observation watermarks. Older generations remain partial and cannot replace content/checkpoints. Actual source flags/locations/resume bindings are reconciled after native writer shutdown.
- Full functional suite: **358 passed, 7 skipped** (5 performance opt-ins, native Codex opt-in, native Warp opt-in). Ruff check/format (110 Python files) and git diff --check PASS.

- Explicit native runtime opt-in: **1 passed** using installed codex-cli 0.166.0 and a disposable offline fixture. Final wheel/sdist build and locked outside-checkout **Python 3.12.12 / SQLite 3.54.1** installation pass. The installed console performed actual native archive/archives/unarchive plus refresh/show/hide/unhide; original flags, history, IDs and neighbor persisted across restart. Wheel SHA-256 `1a131d5d1968c337c97642639809f29017380c3ae8ce73146ecb3d90bb11e5a4`.
- SC-002 first run FAIL: cold 36.893 s and first TUI frame 2.009 s; other warm checks passed. Reader times reached 25–28 s. A subsequent fresh-catalog cProfile run took 9.427 s with readers 0.086–2.612 s; no single cause of the initial reader stall is established. Parent profiling identified redundant serialization/INSERT OR IGNORE for existing sessions; skipped that redundant insert while retaining the same writer transaction and updates. Catalog/discovery/alias/archive regression subset **59 passed** afterward.
- Final isolated SC-002 **5 passed**: cold **6.678 s** (<=10); warm search/navigation **1.314 s**, TUI first frame **1.242 s**, combined filter/sort **0.560 s**, TUI sort **1.299 s** (each <=2). Fresh private catalog; same seed-1 10,000 mixed sessions, requested 1,073,741,824 bytes / actual native bytes 1,130,797,988. OS caches were not flushed and were warmed by the preceding failed/profile runs. No concurrent tests/build/smoke during this measurement; thresholds unchanged. CPython 3.14.2, macOS 27.0.1 arm64, Apple M3 Pro / 18 GiB. Provenance: `{"maximum_finish": 1793888099982, "minimum_start": 1793888095596, "root_as_of": {"claude": 1793888097434, "codex": 1793888098971, "cursor": 1793888099982, "grok": 1793888099598}, "schema": 3}`.
- Final functional suite after the performance change and additional TUI retry coverage: **359 passed, 7 skipped**. Explicit native gate and five corpus gates pass separately; only Warp's native runtime remains externally blocked. Ruff/format of 110 Python files and git diff --check PASS.
- Sole-maintainer self-review: FR-028/spec/plan/task traceability, RED-before-change regressions, closed-set/native-version/alias/containment checks, post-call verification and uncertainty recovery, private journal validation, stale index and late-publication guards, v1/v2-to-v3 migration, CLI/TUI behavior at 80x24, native fixture/installed wheel and unchanged performance targets checked. No dependencies, daemon, direct production native SQLite DML, credential extraction, personal session action, permanent delete or whole-store rollback. Fixture-only edge seeding is explicit. Original T118 and Warp T113/T130/T144 remain open; new archive support does not bypass those gates. Requirements checklist remains read-only (16/16 PASS).


## Phase 12 convergence implementation — 2026-11-06

- T151: 14 initial lifecycle regressions failed before implementation, covering metadata/full
  results published after trash/purge/restore, a separate Python publisher process, empty
  enumeration before restore and interrupted cleanup. Follow-up pending-resume and competing
  cleanup regressions also failed before fixes. Durable revisions/pending owners now guard
  publication in its writer transaction; stale results cannot revive sessions or cache, clear
  newer ownership or prune restored locations. Same-operation recovery releases the owner;
  verified subsequent native reappearance still retains IDs/hidden state. Schema v1/v2/v3
  migration and restored content invalidation are covered. Purge removes owned usage/context
  data without clearing neighboring memberships.
- T152: 12 missing-rollout ancestry/changed-reference regressions failed before the fix.
  Both actions reject symlink/dangling/writable/foreign/non-directory parents before RPC;
  existing safe missing references are supported. Frozen v3 uncertain-operation and unused
  legacy-preview regressions failed before separate reference/history evidence preserved
  compatible recovery while invalidating obsolete unconsumed confirmations.
- Native follow-up: the real 0.166.0 gate initially failed archive_source_changed. Native
  archive/unarchive rewrites missing rollout_path values between the live dated tree and
  archived_sessions. Two synthetic successful/lost-reply rewrite regressions reproduced the
  failure; an unexpected rewrite stayed rejected. Per-intent exact native relocation plus
  existing-ancestor verification and durable current references now pass. Independent native
  gate: **1 passed**, disposable offline CODEX_HOME only; original flags/history/IDs/neighbor
  preserved across restart. Installed Python 3.12 CLI archive/archives/unarchive/refresh/show/
  hide/unhide also passes that actual 0.166.0 gate. Production code contains no native DB DML.
- T153: both corrupted-journal and service-initialization Pilot scenarios failed before
  safe error handling. Archives shows a content-free explanation, preserves the journal and
  returns to the ordinary overview without native RPC. CLI machine codes remain stable.
- T154/T113/T130/T144: **BLOCKED**, previous Computer Use denial for
  dev.warp.Warp-Stable remains in force. No Warp runtime/alternate shell or UI route was
  attempted. URI delivery is not counted as successful handoff. This external gate is
  independent of the five completed code tasks; T118 remains conditional and Grok shared
  indices remain unavailable for cleanup.
- T155: seven initial storage integration/CLI cases failed before implementation. Follow-up
  all-conflicted and missing-source/default-coverage regressions failed before correction.
  Measurements are cached on full refresh, separate from session allocation, deduplicated
  by device/inode across overlapping roots and explicit about as_of/coverage/staleness.
  Stats opening performs no source walk. Empty zero differs from missing/denied/partial;
  symlinks are not followed, conflicts are not counted as known zero, mutations invalidate
  observations, and CLI/TUI/JSON explain whole-source scope and non-reclaimable bytes.
- T156: **22** metadata/CLI/Pilot regressions failed before per-field date provenance.
  All four sources now distinguish naive/aware/absent/invalid dates and mixed histories.
  Naive dates remain ambiguous; known aware bounds survive filters and incomplete ranges.
  Legacy payloads retain existing UTC instants; ordinary refresh adds the new annotations.

Validation after implementation:
- Full functional suite: **427 passed, 7 skipped**, 78.83 s. Five explicit-corpus performance
  gates, one native Codex opt-in and one native Warp opt-in are skipped in the default run;
  performance/native Codex are run separately, Warp remains blocked.
- Ruff check/format: **PASS**, 113 Python files. git diff --check: **PASS**.
- Final isolated SC-002 on schema v4: **5 passed**. Cold **7.652 s** (<=10); warm
  search/navigation **1.769 s**, TUI first frame **1.253 s**, combined filter/sort **0.585 s**,
  TUI sort **1.348 s** (each <=2). Seed-1 mixed 10,000-session corpus, requested
  1,073,741,824 bytes / actual native bytes **1,130,076,804**. Fresh private manager catalog;
  OS caches not flushed, corpus just generated; no simultaneous test/build/smoke workload.
  Subsequent changes are native archive coordinator/fixture-only paths absent from this
  read/search benchmark. Targets unchanged. CPython 3.14.2, SQLite 3.50.4, macOS 27.0.1 arm64,
  Apple M3 Pro / 18 GiB. Provenance:
  {"maximum_finish":1793949084929,"minimum_start":1793949079621,"root_as_of":{"claude":1793949081806,"codex":1793949082488,"cursor":1793949084929,"grok":1793949084304},"schema":4}.
- Wheel/sdist build **PASS**. Fresh outside-checkout locked wheel environment on Python
  **3.12.12 / SQLite 3.54.1** passes help/version/refresh/list/show/stats/resume dry-run,
  hide/unhide, source-storage/provenance output and two trash/restore/purge cycles. All native
  hashes of 40 synthetic sessions remain identical; installed package path is in that venv.
  Wheel SHA-256: fc6f23b3c1f7cce36cbdc9627fa34f42bfd65ba46a380acbc37b30b0e688dbe1.
- The default installed Codex is now **0.167.0**; its explicit native gate refuses the
  version before fixture creation. The supported 0.166.0 binary remains installed and was
  used for the passing native/installed-console gates above. 0.167.0 Archive compatibility
  is not claimed or enabled; exact actual-executable checking remains intact.
- Sole-maintainer self-review: Phase 12 source refs/constitution, observed RED-to-GREEN
  evidence, cross-process lifecycle guards, exact native scope/relocation/uncertainty,
  private state/provenance and retention, additive v4 migration/legacy recovery, public
  CLI/TUI contracts, package isolation and unchanged SC-002 reviewed. No new dependency,
  daemon, cloud/AI call, source repair, personal history operation or unsafe cleanup profile.
  Requirements checklist is unchanged at **16/16 PASS**. .specify/extensions.yml absent;
  pre/post implementation hooks do not apply. Five Phase 12 code tasks are complete;
  the external Warp gate remains unmarked.


## Phase 13 convergence implementation — 2026-11-06

- T157: **10 initial failing regressions** reproduced same-root physical copies losing
  history/usage identity or selecting a different cleanup artifact. Per-location scan,
  catalog evidence and worker IPC now preserve every copy until agreement. Identical
  copies share one row; body/cwd/graph conflicts expose no arbitrary content/usage and
  block actions. Metadata/full/warm/reversed enumeration, disappearing copies, hidden
  state, pickled transport, CLI show/search/stats and 80x24 Pilot checks pass. Resume
  verifies every location/fingerprint; cleanup requires exactly one and rejects a new
  duplicate after preview before any move. Relevant alias/history/launch/cleanup subset:
  **68 passed**. Existing cross-root and lifecycle/archive fences remain intact.
- T158: **7 initial failing regressions** reproduced five durable interruption stages
  plus pre-entry CLI/Pilot recovery. Operation rows are now visible before TrashEntry
  creation, with original operation/target/stage and no claimed recoverable copy. Retry
  uses the original confirmation/scope; terminal items with pending ownership stay
  retryable. Staging intent reserves one trash ID before directory/manifest creation;
  restart validates/reuses it and verifies exact manifests. Cleanup subset: **52 passed**.
  A follow-up corrupt absolute staged-ID regression failed before validation was moved
  ahead of every path access; it now returns invalid_trash_id without outside creation.
  Source/neighbor bytes, no-overwrite, per-item batch outcomes and ownership release pass.
- T160: **8 failing synthetic link regressions** reproduced workspace/session/dangling
  links and intermediate substitution in narrow Grok/Cursor fallback storage. Descriptor
  traversal now binds to the configured root, opens descendants with O_NOFOLLOW and
  checks inode/device before descent. External sentinels are never enumerated/counted;
  unsafe/denied paths remain partial/unknown. Explicit root aliases, overlap dedup,
  cached as_of and no-stats-open I/O are preserved. Storage/discovery/local-alias and
  Cursor/Grok metadata subset: **52 passed**. Existing denied-listing tests still inject
  the same denial, identifying descriptor targets by inode rather than assuming paths.
- T161: **13 expected failing regressions** (after correcting a test-scaffold import)
  reproduced malformed source containers/items and non-boolean control flags. Config
  rejects shapes and enabled types before runtime; SourceRoot validates enabled and
  default_root on construction/deserialization. Invalid config yields safe invalid_config
  with exit 2, without config contents or data-dir creation. Valid enabled=false retains
  prior root generation/as_of and sessions. Config/model/CLI subset: **52 passed**.
- T159/T113/T130/T144/T154: **BLOCKED** by the recorded Computer Use denial for
  dev.warp.Warp-Stable. No runtime attempt or alternative shell/UI route was used. URI
  delivery remains unverified as a conversation handoff. T118 stays conditional; Grok
  shared-index cleanup stays unavailable. Codex 0.167.0 archive is not enabled: the
  approved profile remains actual native 0.166.0.

Release validation:
- `uv run pytest -q --tb=short`: **471 passed, 7 skipped**, 100.67 s. Default skips are
  five explicit-corpus performance gates, native Codex opt-in and blocked native Warp;
  performance and supported native Codex are validated separately below.
- `uv run ruff check src tests`, `uv run ruff format --check src tests` (**114 Python
  files**) and `git diff --check`: **PASS**.
- `uv run pytest tests/acceptance/test_codex_archive_runtime.py
  --codex-archive-executable <retained-0.166.0-binary> -q --tb=short`: **1 passed**, 2.01 s.
  Disposable offline CODEX_HOME only; archive/unarchive cascade, original flags,
  history/IDs, neighbor and restart pass. No personal histories or credentials opened.
- Isolated `uv run pytest tests/performance --corpus <seed-1-corpus> -q -s --tb=short`:
  **5 passed**. Cold **8.533 s** (<=10); warm search/navigation **1.546 s**, TUI first
  frame **1.432 s**, combined filter/sort **0.612 s**, TUI sort **1.344 s** (each <=2).
  Reused synthetic corpus: 10,000 mixed sessions, requested 1,073,741,824 bytes / actual
  native bytes **1,130,076,804**. Fresh private manager catalog; OS caches were warm and
  were not flushed. No concurrent tests/build/native smoke during measurement; targets
  unchanged. CPython **3.14.2**, SQLite **3.50.4**, macOS **27.0.1 arm64**, Apple M3 Pro /
  18 GiB. Provenance:
  {"schema":4,"root_as_of":{"codex":1793953237767,"grok":1793953240395,"claude":1793953237997,"cursor":1793953241162},"minimum_start":1793953235368,"maximum_finish":1793953241162}.
- Wheel/sdist build and outside-checkout locked installed-wheel smoke: **PASS** on
  Python **3.12.12 / SQLite 3.54.1**. Help/version/refresh/list/show/stats/resume dry-run,
  hide/unhide, storage/date provenance and two trash/restore/purge cycles pass for 40
  synthetic sessions; original native hashes remain identical. The installed console
  also passes the actual 0.166.0 archive/archives/unarchive/refresh/show/hide/unhide gate,
  restoring original flags/history/IDs/neighbor across restart.
  Final wheel SHA-256: 40fd49069f363455b24404d671632df71b9d468c28c8b1fa533308bd15b15704.
  Ten changed Markdown documents pass fenced-block and local-link validation.
- Sole-maintainer self-review recorded: FR-004/006/009/014–019/023–026, Phase 13 findings,
  constitution and final docs checked. Reviewed RED-before-fix evidence, per-location
  publication/IPC, exact selected cleanup/resume bindings, durable staging and original
  operation recovery, descriptor boundaries, typed flags, public CLI/TUI behavior and
  compatibility. Schema stays v4; existing IDs/hidden state and legacy recovery remain,
  old unverified location evidence needs refresh. No new dependency/service, production
  native DB DML, personal session operation or new unsafe capability. Requirements
  checklist remains unchanged at **16/16 PASS**. .specify/extensions.yml is absent;
  pre/post implementation hooks do not apply. Four code tasks complete; external Warp
  remains open independently.


## Phase 14 convergence implementation — 2026-11-06

- T162: **6 initial RED cases** reproduced Cursor's per-native-ID graph cache mixing
  accepted physical copies. The cache now uses locator, preserving every copy before
  metadata/full/warm/IPC agreement. Same/different text/graph, reversed discovery, hidden
  IDs, verified disappearance and CLI/Pilot checks pass. Initial relevant subset:
  **45 passed**. A later cache-upgrade Pilot regression failed before TUI startup began
  rebuilding invalidated indices automatically. Normalizer 4 rebuilds old history/search/
  parser caches; stable IDs, hidden flags and journals remain. No native writes by readers.
- T163: **8 RED Pilot cases** reproduced Open selecting the neighbor after refresh or
  manual-guide retry. The modal now captures/shows its original UID/source observation;
  every callback keeps it, and changed/missing observations refuse before child/ticket.
  Current and mocked Warp, filtered/reordered selection, guide retry and Cancel pass.
  Resume/filter acceptance subset: **23 passed**; final request revalidation is unchanged.
- T164: **16 initial valid RED cases** reproduced arbitrary complete usage across copies
  and pending/failed peers. Six other initial conflict fixtures were corrected to vary
  output as well as supplied total, since the adapter derives total from input/output.
  Current-cycle normalized usage evidence now reconciles independently of history, after
  all locations/verified absences publish. Conflicting/pending values remain unknown/partial
  without hiding agreed history. Same-/cross-root Claude receipts, Codex ownership, Grok
  snapshots, publication order, warm IPC, unknown/cancelled peers, disappearance and shared
  healthy receipts pass. A purge-retention regression failed before clearing owned location
  payloads; another failed before preserving shared-event revision guards through the new
  usage publication pass. Alias/history subset after that correction: **71 passed**.
  Schema stays v4; rare aliases retain normalized counters/observations, never native
  transcript copies. Existing within-stream Claude monotonic reconciliation remains.
- T165: **6 RED Pilot cases** reproduced initialization/listing exceptions and invalid,
  missing or denied Trash records/manifests. Safe error handling keeps the healthy overview
  and selection, preserves journal/payload and does not print exception/record contents.
  Progress/TrashEntry/manifest validation rejects corruption rather than showing successful
  empty recovery. Trash/recovery/CLI subset: **59 passed**, with no automatic repair/unlock.
- T166: **5 RED cases** reproduced repeated Grok packets doubling text or reverting a
  completed tool status. Exact eventId replay is now idempotent; conflicting packet payloads
  make history partial, while different IDs with identical text remain legitimate chunks.
  Confirmed-tail/warm replay, order/search/message/tool counts and usage pass. Relevant
  Grok/checkpoint/history/alias subset: **60 passed**. No new guessed native format.
- T167 remains **OPEN / PARTIAL**. Added explicit per-provider native current-terminal
  opt-ins with disposable histories, a child-only isolated HOME/minimal environment and
  macOS sandbox denial of network, keychain, personal stores/shared temporary data and
  outside writes. Parent HOME is unchanged; no credentials/prompt/AI turn/fallback supplied.
  Containment/receipt/exact-version tests: **7 passed**. These began RED for the missing
  harness, group-signal cleanup denial, shared-temp access and three version-prefix cases.
  The harness now cleans only its owned child and rejects unsupported version suffixes
  before resume; containment failure has no unrestricted fallback.
- Explicit installed Claude **2.1.299**, Grok **1.0.70**, Cursor **2026.10.22-27dcf5f**
  current-terminal run: **3 FAILED / unverified**, not passing. None displayed the generated
  marker or proved live cwd; all retained original IDs, no new sessions and neighbor bytes.
  Grok requires authentication during restore, which the offline boundary prevents. Cursor
  attempts a fixed shared /tmp/.cursor directory outside the disposable scope and is denied.
  Claude initially attempted /tmp/claude-<uid>; test-only temp settings now point inside the
  fixture, but loading still was not proved and its remaining startup cause is unverified.
  These limitations are not bypassed using personal stores, credentials or relaxed isolation.
  Warp T113/T130/T144/T154/T159 stays **BLOCKED** by the prior dev.warp.Warp-Stable access
  denial; no Warp attempt/alternate UI or shell route. T118 and Grok shared-index cleanup
  stay unavailable/conditional. Codex 0.167.0 archive is not enabled; SC-003 owner timing is
  still a separate unperformed measurement.

Release checks:
- Final `uv run pytest -q --tb=short`: **546 passed, 10 skipped**, 109.79 s. Default skips:
  five corpus gates, native Codex opt-in, blocked native Warp opt-in, three new native
  current-terminal opt-ins. The latter's explicit failures above remain open, not reclassified
  as passes. Ruff check/format (**123 Python files**) and whitespace checks pass.
- First isolated SC-002: cold **7.556 s** passed, warm search/navigation **2.036 s** failed
  the unchanged <=2 s target; other warm gates passed. A component/profile probe is excluded
  from release timing. It found two complete 10,000-session decodes per list; the second
  only built global short handles. Identity-only projection removes that redundant work,
  retaining typed candidate decoding and hidden/missing/archived collision scope. Existing
  global-handle/pagination/CLI/catalog subset: **49 passed**; full suite repeated afterward.
- Final isolated SC-002: **5 passed**. Cold **9.816 s** (<=10); warm search/navigation
  **1.349 s**, TUI first frame **1.379 s**, combined filter/sort **0.436 s**, TUI sort
  **1.318 s** (each <=2). Same reused seed-1 10,000-session corpus; requested 1,073,741,824
  bytes / actual native bytes **1,130,076,804**. Fresh private catalog; OS caches warm from
  prior reads/profile and not flushed. No concurrent pytest/build/native smoke during this
  final measurement. Targets unchanged. CPython **3.14.2**, SQLite **3.50.4**, macOS
  **27.0.1 arm64**, Apple M3 Pro / 18 GiB. Provenance:
  {"schema":4,"minimum_start":1793964794437,"maximum_finish":1793964800807,"root_as_of":{"codex":1793964798434,"claude":1793964796994,"grok":1793964800807,"cursor":1793964800108}}.
- Wheel/sdist build and locked outside-checkout installed-wheel smoke: **PASS**, Python
  **3.12.12 / SQLite 3.54.1**. Help/version/refresh/list/show/stats/resume dry-run, hide/unhide,
  storage/date provenance and two trash/restore/purge cycles pass on 40 artificial sessions;
  all original native hashes match. Wheel SHA-256:
  **2ad5977c634c78b14056a2c6afdccf716157021c5988b28e401d66ff509abbbd**.
- Supported actual Codex **0.166.0** archive gate: **1 passed**, 2.44 s, disposable offline
  CODEX_HOME. Installed Python 3.12 console also passes archive/archives/unarchive/refresh/
  show/hide/unhide, restoring original flags/history/IDs/neighbor across restart. Fixture
  graph seeding stays test-only; production code contains no native shared-DB DML.
- Sole-maintainer self-review recorded: spec/plan/tasks/constitution traceability, observed
  RED-to-GREEN boundaries, per-location evidence and lifetime scope, pinned resume targets,
  safe recovery errors, packet replay, lifecycle-owned evidence retention, legacy cache
  rebuilding, truthful native acceptance, package/privacy and unchanged SC-002 checked.
  No new runtime dependency/service/schema/native capability. Checklist remains read-only
  **16/16 PASS**; hooks file absent. Five code tasks complete; T167 and earlier independent
  native gates remain open. Documentation links/fences and source/artifact privacy reviewed.
