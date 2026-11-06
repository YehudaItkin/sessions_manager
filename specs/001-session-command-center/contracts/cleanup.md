# Cleanup Contract: hide, trash, restore, purge

**Version**: 1
**Requirements**: FR-013–FR-019, FR-025–FR-027.
[CLI](cli.md), [data model](../data-model.md), [source profiles](sources.md).

## 1. Границы возможностей

Hide/unhide изменяют только manager metadata и доступны без изменения источника.
Trash — удаление истории из локального активного хранилища с сохранением recoverable bundle.
Purge — необратимое удаление только конкретного manager trash entry.

Для Codex 0.166.0 paginated source trash/restore/purge не рекламируются:
native cascade невозможно связать с точным подтверждённым набором.
Менеджер не создаёт видимость удаления через hide и не редактирует общие Codex DB.

Для Claude/Grok/Cursor наличие reader не разрешает cleanup автоматически.
Claude: поддержанный runtime 2.1.299 определяется через bounded --version probe
доверенного executable при отсутствии явного executable_version. Кеш привязан к stat
executable; replacement вызывает повторную проверку. Совместимые JSONL 2.1.x до 2.1.299
проверяются по session ID/uuid/message role/content, а не двум точным patch-версиям.
Grok/Cursor поддерживают автоматический bounded --version probe той же доверенной
границы для 1.0.70/2026.10.22-27dcf5f; проверенная native структура по-прежнему обязательна.
Наличие grok.db/общего session_search.sqlite не разрешает file-only trash: индекс
содержит отдельную копию истории, а scoped native cleanup/restore не доказаны.
Известный per-session workflows/ включается только при согласованном runId/filename,
терминальном status и обычных .json/.js файлах; orphan scripts, symlinks и неизвестная
структура отклоняются. Внешний scriptPath не обходится и не удаляется; JS не исполняется.
Неизвестные версии, unsafe executable и failed probe остаются unavailable.
synthetic используется только fixtures. Restore/retry в новом процессе повторно resolves version.
Capability появляется только после fixture-backed доказательства session-owned artifact set,
известной topology, writer/quiescence conditions и no-overwrite восстановления.
Неизвестный формат, shared dependency без безопасной границы, unsupported no-replace или
другой device между source и manager vault возвращает unavailable/unsafe без изменения source.

## 2. Preconditions

Перед preview:
1. Разрешить точные стабильные IDs и текущие native locations.
   Требуется единственная физическая location (root + locator), даже для одинаковых
   копий внутри одного root. Повторное чтение обязано совпасть с показанной location,
   fingerprint и подтверждённым inventory; первый найденный native ID недостаточен.
2. Построить только разрешённый адаптером конечный список owned artifacts/dependencies.
3. Проверить uid, containment, типы, canonical roots; не обходить symlink для удаления,
   не брать project files и общие DB/history/cache других сессий.
4. Получить per-session activity evidence. Known active запрещён, force отсутствует.
5. Показать ID/provider/число/известный объём/unknown, эффект и доступное восстановление.

Перед commit:
- Сверить action, exact targets, fingerprint, profile/version и expiry confirmation plan.
- Получить exclusive manager operation lock, исключающий две операции менеджера над bundle.
- Для unknown потребовать утверждение владельца: выбранные сессии закрыты и не будут
  открываться до окончания операции. Это предусловие, а не обнаруженный native lock.
- Проверить известные runtime records, process identity, open writer evidence и стабильность
  source generation. Наблюдаемый writer/изменение запрещены даже при --assert-closed.
- Advisory lock менеджера и stat check не называются блокировкой внешних писателей.
  Профиль, которому нужна недоступная native coordination, mutation не разрешает.

Гарантии ниже действуют при выполнении объявленных условий закрытости. Менеджер не обещает
остановить процесс с уже открытым FD и никогда сам не завершает native runtime.

## 3. Trash protocol

1. Создать operation_id и private staging/trash entry без повторного использования ID.
   Persist immutable manifest: source identity/profile, exact artifacts, original modes,
   fingerprints, expected destinations. Token consumed атомарно в manager catalog.
2. Скопировать полный bundle в приватный backup; проверить bytes/hashes/структурную
   целостность. Для DB не терять committed WAL. Файлы и manifest fsync, затем parent dirs.
   До BACKUP_READY source не меняется.
3. Повторно проверить source и quiescence. При изменении остановиться без native mutation.
4. Переместить exact artifacts в private payload тем же device через Darwin
   renameatx_np(RENAME_EXCL) / эквивалентную проверенную no-replace операцию.
   Для многофайлового bundle каждый переход журналируется. Никакого recursive удаления
   общего parent/project и никакого whole-DB rollback.
5. После каждого шага fsync соответствующих directories и durable progress. Backup остаётся
   recoverable до проверки перемещённого payload; при подозрении сохраняются обе версии.
6. Проверить, что выбранные active artifacts отсутствуют, payload полный, соседние сессии
   не затронуты. Лишь затем state=trashed; активный search membership исключается.
   Redundant staging copy можно убрать только после доказанного сохранения payload.

Same-device ограничение первой версии явно отражается в capabilities.
Не делать copy+unlink через другой том под видом atomic rename.
Временные staged данные не сканируются как новые native sessions.
Source-specific shared caches либо имеют доказанное безопасное поведение, либо mutation
профиля остаётся недоступной; stale ghost row не выдаётся за полностью успешную уборку.

## 4. Restore protocol

1. Новый preview/confirmation для точных trash IDs, проверка payload hashes и версии.
2. Исходный configured namespace/root всё ещё принадлежит пользователю; original target
   paths разрешены, parent доступен, нет symlink/path substitution.
3. Любой существующий target — conflict, без overwrite. Отдельный exists() не является
   достаточной защитой: создание/move само MUST быть atomic no-replace.
4. Восстановить original native identity, полное содержание и права не шире исходных;
   проектные файлы не восстанавливаются и не изменяются.
5. Проверить восстановленный набор, затем отметить restored и обновить catalog.
   Trash recovery data сохраняются до доказанного завершения.
6. Если новое состояние native source несовместимо, оставить entry и выдать conflict/
   recovery_required; не откатывать всё source storage.

Unknown/new source schema после upgrade отключает restore, а не вызывает угадывание.
Missing parent/root возвращает понятную причину; произвольный --destination не разрешён.

## 5. Purge protocol

- Принимает только trash IDs, не source IDs и не filesystem paths.
- Требует отдельный точный irreversible preview/confirmation; hide/delete tokens непригодны.
- Не выбирает `all`/glob автоматически и не удаляет trash по возрасту.
- Удаляет только проверенные manager-owned payload/backup этого entry; path traversal,
  symlink и изменившееся содержимое дают отказ.
- Повтор purge возвращает уже записанный итог. Interrupted purge остаётся resumable по
  тому же op_id, с перечислением оставшегося payload.
- Receipt может сохранять минимальные ID/состояние для idempotency, но не transcript.
- Нет обещания forensic secure erase или удаления cloud/native-memory копий.

## 6. Crash, retry и batch

Filesystem и SQLite journal не атомарны вместе. Trash list обозначает незавершённые
операции как recovery_required. При `trash retry OPERATION_ID [--assert-closed]`
recovery сверяет manifest, expected hashes/locations и реальные файлы.
Операция доступна и до создания TrashEntry/manifest: строка kind=operation содержит
исходные operation_id/target_id, stage, trash_id=null и recoverable_copy=false.
В TUI Retry (x) показывает прежние цели и требует closed assertion для неизвестной
активности trash. Restore/purge такой строки недоступны; новый confirmation scope
не создаётся. Зарезервированный trash ID сохраняется до создания directory/manifest,
валидируется до файлового доступа и повторно используется только с exact manifest.
Если terminal item уже сохранён, но lifecycle owner ещё не снят, Retry остаётся видимым
до согласования результата. Исходный journal не удаляется ради разблокировки.
Crash между rename и записью стадии не
считается автоматически ни успехом, ни потерей. Если есть различающиеся версии, обе
сохраняются и нужен явный recovery/restore, а не скрытый overwrite.

До source change: failed_no_change/cancelled.
После source change: recovery_required, либо доказанный per-target terminal result.
Retry использует прежний operation/target; повторная dynamic selection запрещена.
Batch не является общей атомарной транзакцией: отдельный итог каждого target, успешные
entries доступны для restore, непройденные остаются видны. Exit 3 для частичного результата.

## 7. Обязательные проверки до включения mutation

Только искусственные source roots и наблюдаемые neighbor hashes:
- cancelled preview/expired token/stale fingerprint не меняют ни одного source byte;
- known active block; unknown без assertion block; PID reuse не даёт ложного active/inactive;
- low disk, access denied, unsupported device/no-replace, symlinks/hardlink ambiguity;
- fault после каждого copy/hash/fsync/rename/journal шага и повтор того же op_id;
- multi-artifact partial failure, отсутствующий/новый target, restore race;
- live WAL, source mutation during snapshot, uncooperative writer simulation;
- source companions и neighboring sessions сохраняются;
- Codex unsafe cascade и Grok remote delete никогда не вызываются;
- purge не может выйти за entry directory или удалить native/cloud историю.

Исследование формата не является прохождением этих тестов.


## Convergence confirmation and feasibility amendment — 2026-11-05

Before the first native rename, re-discover and compare the complete confirmed
bundle/profile/artifact set, including newly appearing companions. Confirmed
restore/purge entry digest and state must match before starting a new operation;
a stale confirmation requires a new preview. An operation already in progress
reconciles its own durable journal/verified payload rather than treating its
intentional partial relocation as a newly discovered bundle.

Purge of a trashed cached session also removes its whitelisted JSONL parser
checkpoint, leaving neighbors and restored live histories intact.
Grok shared-index feasibility is concluded as unavailable for the current
profile: no verified native revision-bound local reversible primitive exists.
Known shared DB/WAL/SHM paths are guarded in home/sessions/workspace layouts.
The standalone local bundle profile retains crash/retry/restore support.
Native permanent/remote delete, direct shared DB mutation and whole-DB rollback
remain excluded; Codex native descendant/revision/recovery gate is unchanged.


## Phase 10 lifecycle amendment — 2026-11-05

Derived transcript/search/parser cache deletion requires the selected trash entry to own
sessions.current_trash_id. Purging an older restored backup leaves a newer trash lifecycle
and its cache intact. Verified full native history can reactivate the same manager ID
and hidden state; metadata/header/projection-only discoveries cannot. Restore retains
its exact destination/no-overwrite checks.

After the terminal receipt commits, final directory/fsync failure retains state=purged
with cleanup_pending=true and retry/inspect options, never restore. CLI commit/retry exits
nonzero while pending. Restart retry uses the original operation and accepts only the
original verified manifest or an empty/missing entry directory; unknown new contents are
refused. Pre-receipt partial purge still uses manifest/payload recovery as before.


## Native Codex archive contract — 2026-11-05

Archive/Unarchive are separate from manager trash and permanent deletion (FR-028).
Preview binds root/executable/profile, exact root + descendant IDs, history revision and
per-ID prior archived state. The same private operation lock serializes manager mutations.
All affected sessions must remain closed (--assert-closed); active writers and ambiguous
locations block commit. Native archive may partially succeed, so each confirmed ID is
verified and progress persisted. Retry uses the original immutable scope; changed graphs
or unrelated state are conflicts. Unarchive of a manager operation restores its original
archived flags; an independently archived session can be unarchived individually. A
pre-archived descendant is never restored implicitly. CLI/TUI show partial/retry results.
Private native reads remain read-only; only native RPCs change archive flags. No history
files/shared DB rollback/delete, credential copying or AI requests.


Native unarchive in the verified 0.166.0 build also cascades; this was observed in the
fixture gate. Reconciliation traverses parent before child and re-archives prior archived
children when necessary. Temporary changes remain confined to the full preview scope.
A durable per-call intent allows a lost response/crash to accept only prior/attempted
flags within that exact subtree; changed graph/history/unknown flags conflict. Operation
startup failure before a native archive request is failed_no_change and allows a new
preview. After an uncertain request, retry/recovery is mandatory. Pending operation IDs
block native resume, including fresh single-source request construction.

Snapshot size is bounded to 10,000 IDs, cycles/unknown profiles fail closed. Closed-session
assertion is mandatory and does not bypass observed handles or establish a native revision
lock. Permanent/trash deletion T118 and the separate Warp runtime gates remain unchanged.


## Phase 12 publication and reference boundaries — 2026-11-06

Each cleanup item owns a persisted lifecycle revision/pending operation. Old reader
results cannot revive a tombstone, clear a newer trash owner, repopulate purged derived
caches or mark a restored session missing. The check and publication share one SQLite
writer transaction. Pending/revision-mismatched roots remain partial without pruning.
New Open/cleanup is refused while the original item requires recovery; retry of the
same operation releases its pending owner only on a terminal result. Verified later
native reappearance still preserves manager ID/hidden state. Restore requires reindexing;
shared/neighbor data remain protected when clearing owned derived usage on purge.

Archive/Unarchive validate existing ancestry of missing rollout references, rejecting
symlinks, writable/foreign parents and non-directory components before RPC. New previews
bind both history and reference evidence. Unused legacy previews return
archive_preview_outdated and require new preview; uncertain legacy operations can retry
the same IDs against original history/flags plus current trusted path checks. No new
IDs, source creation, direct native DML or forced rollback is introduced.


Phase 12 native fixture follow-up: Codex 0.166.0 rewrites missing rollout references
between sessions/YYYY/MM/DD/rollout-<date-time>-<thread-id>.jsonl and
archived_sessions/<same-basename> during archive/unarchive. Preview and the first call
still require exact unchanged references. After a persisted per-call intent, observation
accepts only this verified transition for that affected ID with the expected flag,
unchanged history/graph and trusted existing ancestors. Newly created native directories
are allowed; replacement of previously proven common ancestors is not. Current references
are validated and journaled for same-scope retry; unexpected rewrites remain conflicts.
Reference evidence stores path, revision and existing ancestor stat identity, not bodies.
