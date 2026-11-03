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
Grok/Cursor требуют явные 1.0.70/2026.10.22-27dcf5f и проверенную native структуру.
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
