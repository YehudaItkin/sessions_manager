# Data Model: CLI-центр AI-сессий

Current manager catalog version: **4**; native schemas are never migrated.

**Date**: 2026-11-02
**Basis**: [spec.md](spec.md), [research.md](research.md).
Это логическая модель; SQL migrations и реализация создаются на следующем этапе.

## 1. Хранение и общие типы

Собственные данные: `~/Library/Application Support/sessions-manager/`; явный `--data-dir`
переопределяет каталог. Config — config.toml, каталог — catalog.sqlite3, корзина — trash/,
одноразовые launch manifests — launches/. Никаких данных в репозитории или cwd проекта.
Новые директории 0700, файлы/DB/WAL/SHM 0600, umask 077; существующий чужой/небезопасный
data-dir вызывает отказ без автоматического chmod пользовательских каталогов.

Каталог SQLite использует один writer и отдельные read connections для workers/UI.
Foreign keys, параметризованные запросы и явные транзакции обязательны. Миграции только
собственного каталога; native schemas никогда не мигрируются менеджером.

- Все ID — строки с типом/namespace; пользовательский ID не является номером строки.
- Время: UTC epoch milliseconds либо null, плюс provenance и timezone-confidence.
  Вывод — локальный timezone; неоднозначное время не проходит точный фильтр периода.
- Счётчики: неотрицательный integer либо null; bool не принимается как число.
- Полнота: complete / partial / unavailable / stale с причиной и as_of.
- Возможность действия: supported / unavailable / unsafe с machine-readable reason.
- Native paths — абсолютные; нормализация пути не заменяет проверку владельца, symlinks
  и допустимой области операции.
- Plaintext истории допустим только в приватном каталоге/корзине/явном пользовательском
  выводе. Diagnostics содержат коды и агрегаты, не содержимое событий или секреты.

## 2. Источники и сессии

### SourceRoot

| Поле | Значение |
| ---- | -------- |
| root_id | Стабильный UUID локальной конфигурации |
| provider | codex / claude / cursor / grok |
| namespace_id | Логический профиль одного источника, не путь и не прочитанный account token |
| path, root_kind | Native home или явно добавленное history location |
| enabled, default_root | Управление областью сканирования |
| reader_profile, schema_fingerprint | Проверенный формат, независимо от версии executable |
| executable_path, executable_version | Разрешённый native CLI либо null |
| resume_context | Доказанная связь этого расположения с native CLI; иначе view-only |
| health, last_scan_id | Состояние и актуальность |

Несколько расположений одного namespace могут быть aliases одной истории; отдельный
профиль задаётся явно. Перемещение корня не меняет namespace. Добавление произвольной
копии не даёт права продолжать её через другой native home.
CODEX_HOME/CLAUDE_CONFIG_DIR могут передаваться только как проверенные context overrides,
без сохранения всего environment или credentials.

### Session

| Поле | Значение |
| ---- | -------- |
| session_uid | Детерминированный полный UUID от namespace + native_id |
| display_id | Стабильный полный человекочитаемый handle; краткая форма только при уникальности |
| namespace_id, native_id | Составная уникальная принадлежность |
| title, preview, project_id, model | Только whitelisted значения; null допустим |
| created_at, last_activity_at | Значение, происхождение, timezone-confidence |
| hidden | Постоянный manager-only признак |
| presence | present / source_unavailable / missing / trashed / purged |
| activity | active / inactive / unknown и ссылка на ActivityEvidence |
| capabilities | Независимые metadata/history/search/resume/usage/cleanup с причинами |
| current_generation | Из какого scan получены сведения |

В обзоре display_id и native_id обозначены раздельно. Визуальное сокращение ID не меняет
его значения; show и JSON содержат полные ID. Сокращённый native ID никогда не подставляется
в LaunchRequest или подтверждение cleanup вместо полной identity.

При отсутствии native_id назначается постоянный surrogate по проверенной identity
артефакта; наличие surrogate не разрешает resume/delete без доказанной связи.
Тот же native_id разных providers/namespaces не смешивается. Совпадающие aliases не
дублируют строку. Несовместимые содержимые с одной identity дают identity_conflict;
не выбирается случайная копия, а опасные действия отключаются.

### SessionLocation и Project

SessionLocation связывает session_uid, root_id, native locator, completeness,
artifact fingerprints и preferred/alias/conflict status. Fingerprint для инвалидации
включает dev/inode/size/mtime_ns и native revision/cursor; это не доказательство inactivity.
Для cleanup дополнительно нужны полные hashes и manifest.

Project содержит project_id, нормализованный cwd, display name и path_available.
Cwd берётся из native metadata, не угадывается из encoded directory name.
Выбор нового cwd для resume меняет LaunchRequest, а не молча переписывает native историю.

### ActivityEvidence

Поля: session_uid, evidence_kind, observed_at, native record reference, pid,
process_start_identity, resolved executable, confidence, status.
Только положительная проверенная связь записи с живым процессом даёт active.
Отсутствие процесса/lock не доказывает отсутствие другого runtime: обычно unknown.
PID reuse и устаревшая запись не дают положительного статуса.

## 3. История, индекс и поколения

### HistoryEvent и SessionEventMembership

HistoryEvent: event_uid, provider-native event identity/scope, role
(user / assistant / tool_call / tool_result / system / unsupported), order_key,
timestamp/provenance, text, structured display payload, native locator, completeness.
SessionEventMembership: session_uid, event_uid, branch/turn identity, ordinal.

Сохраняются порядок и native graph membership. Стриминговые chunks одного сообщения
объединяются; альтернативные представления не дублируются. Tool-only записи не считаются
user messages. Неподдержанный узел явно снижает полноту; он не становится пустым ответом.
В Cursor обходится только достижимый граф; секретные meta properties не копируются.
Reasoning/внутренние opaque payloads не нужны для обзора и не индексируются как чат.

### ScanGeneration и SearchChunk

ScanGeneration: scan_id, root_id, state (running / complete / partial / failed / cancelled),
started_at, finished_at, enumeration/history/search completeness, source revision range,
reader_version, normalizer_version и diagnostics codes.

SearchChunk: chunk_id, session/event membership, field_kind, folded_text, generation.
Folded text = str.casefold(); native text и диапазоны отображения хранятся отдельно.
FTS5 trigram с external content ускоряет кандидатов, final instr проверяет буквальную
подстроку. Никаких пользовательских wildcard/FTS operators. Для коротких запросов —
точная проверка по отфильтрованной выборке; отмена не выдаётся за полный результат.
SearchChunk — целое логическое поле или сообщение. Разбиение большого сообщения на
физические страницы не должно терять совпадение через их границу; без такой проверки
индекс не может называться полным.

Публикация одной законченной session generation атомарна в собственном каталоге.
Полная удачная enumeration может пометить исчезнувшие записи missing; ошибка корня —
только stale/source_unavailable, не mass deletion. Identity/hide tombstone сохраняется,
чтобы повторное обнаружение не меняло ID. Cached history — индекс, не обещание
восстановления native разговора. Purge удаляет его manager search membership.

Refresh полностью перечисляет настроенные корни выбранных источников. Фильтры проекта
и даты ограничивают только вывод, не enumeration/reconciliation. Только успешный полный
scan конкретного root может установить missing в его области; невыбранные roots сохраняют
прежние records/generation/as_of. Отфильтрованный результат не является полной enumeration.

## 4. Статистика

### UsageFact и UsageMembership

UsageFact: fact_uid, provider, verified identity_scope, native_request_id,
owner_native_session_id (если доказан), model, input/output/cache-read/cache-write/reasoning/
total integers-or-null, completeness, source evidence revision.
UsageMembership: session_uid, fact_uid, origin/fork/copy evidence.

Один API response/message — один факт, даже если находится в нескольких histories.
Разные request IDs с одинаковым текстом остаются разными фактами. Native identity может
быть глобальной или namespace-scoped только по проверенному контракту источника.
Конфликтные receipts не объединяются арифметически: сохраняется incomplete evidence.

### UsageSnapshot

Поля: session_uid, accounting_scope, epoch, native revision, category values,
completeness, summability (disjoint / overlapping / unknown), covered fact set/cursor.
Авторитетный snapshot заменяется новым, не складывается с собой или receipts того же scope.
Локальный context occupancy хранится отдельной метрикой с kind=context, не lifetime usage.

Правила:
1. Per-session total описывает полную историю выбранной сессии.
2. Сводка объединяет уникальные подтверждённые факты; это не сумма session totals.
3. Snapshot-only scopes суммируются только при доказанной независимости; иначе исключаются
   из безопасной суммы с явным incomplete/non_summable покрытием.
4. Известные 0 сохраняются. Нет поля — null, если профиль не доказывает семантику default zero.
5. Total не включает cache/reasoning повторно. Native subset/disjoint semantics нормализуются.
6. Для каждой категории показываются selected_sessions, known_sessions, incomplete_sessions,
   known_fact_count и included/excluded snapshot scopes.
7. В группировке факт, принадлежащий нескольким различным группам выбранных сессий,
   попадает в явную группу shared_usage. Общий итог считается независимо по union, а не
   суммой потенциально пересекающихся history totals.
8. Фильтр периода отбирает сессии по последней активности; это не расход событий за период.
9. Message count учитывает нормализованные user/assistant events с доказанными identities,
   отдельно от tool events; неполные/неоднозначные данные сохраняют признак partial.

## 5. Корзина и журнал

### OperationPlan

Поля: plan_id, action (trash / restore / purge), exact ordered target IDs, fingerprints,
source profiles, activity preconditions, required_closed_assertions, byte estimate/
unknown flag, created_at/expires_at, confirmation_token_digest, consumed_at.
Token действует 5 минут, не является generic --yes, связан со всем показанным набором
и действием. Изменение набора/источника/профиля требует нового preview.

### TrashEntry и OperationItem

TrashEntry: trash_id, session_uid, operation_id, original namespace/locators, owner_uid,
source_profile, manifest_version, artifact inventory + hashes + original modes,
snapshot_verified_at, state, conflict_reason. Путь payload всегда вычисляется из ID
внутри manager trash, не принимается из пользовательского произвольного пути.

OperationItem: op_id, target_id, action, durable stage, per-artifact progress, errors,
recovery options и timestamps. Между каталогом и filesystem нет фиктивной общей транзакции.

Основные переходы:
- live/hidden -> preview -> backup_ready -> removing -> trashed;
- trashed -> restore_preview -> restoring -> restored;
- trashed -> purge_preview -> purging -> purged;
- после source change любая ошибка -> recovery_required/conflict, не generic success;
- до source change ошибка -> failed_no_change/cancelled.

Повтор по op_id возвращает/завершает тот же результат, не выбирает объект заново.
Batch содержит отдельные OperationItem. Crash recovery сверяет manifest и реальные
артефакты: предположение, что журнал и rename всегда успели вместе, запрещено.
Codex paginated не создаёт TrashEntry, потому что mutation capability отсутствует.
Подробные пред-/постусловия — [cleanup contract](contracts/cleanup.md).

## 6. Запуск

### LaunchRequest

Поля: launch_id, random ticket digest, session_uid, source fingerprint,
history_locator, absolute executable, argv, cwd, allowlisted context overrides,
target (current / warp), manager data-dir, owner_uid, created_at/expires_at, state и safe error code.

history_locator фиксирует исходные namespace/native ID/SessionLocation/workspace context;
cwd — выбранная существующая рабочая папка выполнения. Смена cwd не меняет history_locator
или session_uid. LaunchRequest создаётся только при подтверждённой привязке истории
к native resume в выбранном cwd; неподтверждённый случай не создаёт Warp ticket.

ManualResumeGuide — пользовательский результат отказа, не LaunchRequest и не запись
диагностического журнала. Содержит источник, полный native ID при наличии, исходный locator,
исходный/запрошенный cwd, reason и проверенные шаги/команду справки. Он показывается вместе
с другой папкой/отменой; не сохраняет credentials и не выполняет непроверенные команды.

В manifest нет скопированного окружения, credential values или transcript.
Ticket случайный, одноразовый, срок 120 секунд. Состояния:
requested -> claimed -> handoff_attempted -> child_exited / exec_failed;
requested -> expired / delivery_failed.
URI delivered не равно claimed, а handoff_attempted не равно conversation_loaded.
Удаляются только manager-owned launch artifacts после завершения/expiry, не session trash.
Подробности — [launch contract](contracts/launch.md).


## Convergence storage amendment — 2026-11-05

- events.logical_uid separates native event identity from content-revision keys;
  per-membership context and immutable revision bodies prevent fork mixing.
- generations.payload adds actual started_at/finished_at, enumeration/history/
  search/usage completeness and source revision ranges. Older rows can remain null.
- jsonl_cursors(root_id,path,uid,payload) is a private parser cache. The compressed
  payload contains only whitelisted supported JSONL fields, version, fingerprint,
  confirmed newline offset/ordinal and SHA-256 prefix. It follows the owning
  session's retention; purge removes it when purging that cached session.
- ContextMetric adds source_profile, root/source revision, observation time and
  completeness. Unknown counters remain null and never become lifetime receipts.

Migrations are additive and affect only the manager catalog. Normalizer 3 rebuilds
old history/search caches from configured native sources; unknown or unavailable
sources remain explicitly partial/stale. Invalid persisted model values raise a
content-free catalog_record_invalid error without automatic repair or data loss.


## Phase 10 storage amendment — 2026-11-05

- locations.payload is nullable for old/default single-location rows. Multi-location namespaces
  retain the native session metadata/capabilities, current cycle and metadata/full stage;
  versioned identity digests include conversation graph membership and content. No extra
  transcript bodies are stored there. A new refresh invalidates prior-cycle agreement.
- sessions.current_trash_id is nullable and owns the current trashed derived snapshot.
  Trash sets it, verified restore/reappearance clears it, and purge clears derived data
  only when the selected entry owns that snapshot. Stable IDs and hidden flags survive.
- LaunchRequest.alias_bindings is an additive list of agreed root descriptors, locators
  and native fingerprints. Older requests default to an empty list; a changed catalog
  binding requires a fresh request, and all copies are checked before exec.
- OperationItem.cleanup_pending distinguishes final manifest/directory/fsync work from
  a committed purged receipt. Such results retain state=purged, expose retry/inspect and
  return a nonzero CLI status until cleanup completes; no recoverable payload is claimed.

All migrations remain confined to the private manager catalog. Existing location rows
without evidence require rediscovery before multi-location actions can be supported.

The location/owner migration and user_version=2 are committed in one transaction.
Existing v1 sessions/hidden state/locations are retained. Older v1 binaries reject v2
from its header before writing, rather than attempting positional inserts with the old
column count. Downgrade requires a separately retained v1 catalog; use the current binary
with upgraded catalogs. Foreign/future application/schema IDs remain rejected.


## Native archive state — 2026-11-05

Session.extra.archived is a native Codex flag, separate from manager hidden and presence.
Existing payloads without the flag are active. Ordinary list/stats exclude archived rows;
the archive list retains their stable IDs and hidden flags. Manager archive plans/progress
store root/session identity, exact members, original flags and per-operation recovery state
in private dedicated tables. They retain no transcripts and share the cleanup operation
lock. Read-only refresh never changes native archive state.


Archive adds catalog schema v3: v1/v2 records migrate without losing IDs/history/hidden
state; missing archive/unarchive capabilities default unavailable until refresh. Older
binaries reject v3 before writes. Downgrade requires a retained older catalog.

`native_archive_plans` stores token digests, action/root selector, private snapshot/prestates/
desired flags, expiry and consumed operation ID. `native_archive_operations` stores that
immutable plan, last verified flags, a durable intent before each native call, whether a
request may have started, and running/complete/recovery_required/failed_no_change outcome.
Typed validation rejects malformed persisted scope/flags before RPC, without repair.
Journal contains metadata/IDs/hashes, never transcript copies or credentials.

SessionLocation payload also retains post-archive metadata and native_archive_observed_at
watermarks. Publication begins a SQLite writer transaction before loading this evidence.
Readers started before the verified observation cannot undo it, replace history/usage or
parser checkpoints; that generation is explicitly partial. A later fresh reader retains
the watermark. Archive conservatively marks cached content/usage stale for reindex rather
than assigning a fresh native fingerprint to old cached content. TUI refreshes Codex
after completion; CLI reindex follows the existing runtime stale-cache gate.


## Phase 12 storage and date provenance — 2026-11-06

Schema v4 atomically adds sessions.lifecycle_revision (integer, default 0),
sessions.lifecycle_pending (nullable original operation ID) and source_storage(root_id,
payload). v1/v2/v3 session IDs, hidden state, history, locations and operation journals
are retained. Older binaries reject v4 before writes; downgrade needs a separately
retained older catalog. Native files are not migrated or restored by a manager downgrade.

Scan results carry their prepared lifecycle revision map privately across workers.
Publication under BEGIN IMMEDIATE rejects a changed/pending session, including late
content/search/usage/checkpoint data, and cannot prune locations for that partial root.
Cleanup increments the revision before work and on terminal completion; a crash retains
the operation owner. Restore marks history/search stale and usage partial until refresh.
Purge of the owning entry removes its usage/context memberships and orphan facts as well
as transcript/search/checkpoint data; neighboring memberships remain retained.

source_storage stores bounded file facts keyed by device/inode (size and mtime only),
observation time, known/complete/stale and reason. Partial/failed refresh preserves prior
cached observations and as_of; native mutations invalidate completeness. Total bytes are
an independent source metric, not a sum/allocation of session sizes or reclaimable bytes.
Overlapping observations are deduplicated; conflicting file observations are excluded
with partial coverage (all-conflicted is null, not a known empty zero).

Session.extra.date_provenance maps created_at/last_activity_at to confidence/reason;
ambiguous_native_dates records naive native timestamps even when aware bounds remain.
Reasons distinguish timezone_not_recorded, not_recorded and invalid_timestamp. Only
known UTC instants participate in period filters/ranges; ambiguous records make the
range incomplete. Legacy payloads keep their UTC values until ordinary refresh annotates
them. Native archive snapshots add a separate validated per-ID references hash; old
uncertain operations retain their original history revision semantics for safe retry.


Phase 12 native fixture follow-up: Codex 0.166.0 rewrites missing rollout references
between sessions/YYYY/MM/DD/rollout-<date-time>-<thread-id>.jsonl and
archived_sessions/<same-basename> during archive/unarchive. Preview and the first call
still require exact unchanged references. After a persisted per-call intent, observation
accepts only this verified transition for that affected ID with the expected flag,
unchanged history/graph and trusted existing ancestors. Newly created native directories
are allowed; replacement of previously proven common ancestors is not. Current references
are validated and journaled for same-scope retry; unexpected rewrites remain conflicts.
Reference evidence stores path, revision and existing ancestor stat identity, not bodies.


## Phase 13 location and recovery observations — 2026-11-06

Physical identity evidence is keyed by (root_id, locator), including duplicate native IDs
inside one root. Scan/IPC history and usage buffers retain these keys until agreement;
existing locations.payload stores each copy's native metadata and versioned digest.
The stable manager UID/hidden state does not change. Matching copies share one row;
conflicting copies expose no arbitrary history/usage. Old multi-location rows without
matching evidence require refresh before resume, and cleanup requires one location.
Catalog schema remains v4; no new table, column, migration or dependency is needed.

OperationItem.trash_id can reserve staging before TrashEntry exists. Recovery must validate
it before any path use, reuse that exact ID, and verify any existing immutable manifest.
trash_list is an additive union: kind=trash rows retain trash_id; kind=operation rows have
trash_id=null, item_id=operation:<operation_id>:<target_id>, target_id and the original
operation_id. Both expose stage and available_actions. A pre-entry operation has
recoverable_copy=false; retry_same_confirmation continues the original journal and targets.
Terminal items that still own lifecycle_pending remain retryable until reconciliation
clears that owner. No journal deletion or generic unlock is a recovery mechanism.

SourceRoot.enabled/default_root require exact booleans on construction/deserialization.
Config sources requires an array of objects before runtime preparation; malformed shapes
or flags yield safe invalid_config/exit 2. Disabled roots retain prior generation/as_of.


## Phase 14 normalized evidence — 2026-11-06

locations.payload adds nullable usage for rare alias groups: normalized UsageResult
receipts/snapshots/memberships and context observations, without native transcript bodies.
Semantic agreement compares lifetime scopes/ownership/values/completeness, excluding
physical stat revisions and context timestamps. The existing ledger is populated only
after all locations/verified absences reconcile, so a provisional copy cannot rewrite
another session's shared request fact. Retaining normalized evidence permits recovery of
the surviving location's own counters when the absent peer publishes last. No schema
change: user_version stays 4; old location payloads require refresh before usage agreement.

Session.extra.usage_conflict is usage_identity_conflict or usage_binding_unverified.
These suppress unverified lifetime values and mark coverage partial while preserving
independently agreed history. Source/path ordering never selects a supposedly newer total.
Cursor context occupancy remains separate. Purge of the current lifecycle clears owned
location payloads as well as ledger/context/parser/history data; an older entry cannot
clear newer evidence. Normalizer 4 rebuilds old history/search/parser caches, retaining
stable IDs, hidden state and journals.
