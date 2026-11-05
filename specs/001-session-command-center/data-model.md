# Data Model: CLI-центр AI-сессий

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
