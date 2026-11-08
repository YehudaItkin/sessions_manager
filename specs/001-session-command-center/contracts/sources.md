# Source Adapter Contract

**Version**: 1
**Evidence**: [research.md](../research.md#r2-независимые-возможности-источников).
Источники — данные, не исполняемые plugins. Собственные readers входят в один пакет.

## Общая граница

Адаптер предоставляет probe, discover, read_history(page), read_usage, activity evidence,
build_resume и prepare_cleanup_bundle. Он не выбирает UI, не спрашивает подтверждение,
не пишет manager catalog самостоятельно и не выполняет arbitrary shell commands.
Cleanup mutation запускает общий coordinator после adapter-specific proof.

Результат содержит native identity, normalized records, revision/cursor, per-capability
status, completeness и безопасные diagnostic codes. Пустой набор возвращается как complete
только после успешного чтения корня. Optional неизвестные записи пропускаются с учётом
полноты; неизвестная критическая структура делает соответствующую возможность unavailable.

Каждый fixture-backed профиль фиксирует provider, CLI version evidence, native schema/
record-version predicates, reader_version, allowed artifact types и capabilities.
Только номер установленной программы недостаточен. Upgrade не включает mutation автоматически.

build_resume получает исходный history_locator отдельно от execution cwd. Указанные ниже
native argv действуют только при подтверждённой связи с выбранной историей; перенос проекта
не разрешает слепую подстановку нового cwd в workspace-scoped lookup. Неподдержанная или
неподтверждённая комбинация возвращает причину и ManualResumeGuide без child/ticket,
сохраняя возможность выбора другой папки/отмены. Native data не переносятся, ID не заменяются.

Стандартные корни: CODEX_HOME или ~/.codex; CLAUDE_CONFIG_DIR или ~/.claude;
~/.cursor/chats; ~/.grok/sessions. Другие расположения добавляются явно.
Полный обход home/диска, browser/desktop/ACP stores и private credentials исключены.
Нестандартное расположение остаётся view-only, пока связь с native resume не доказана.
В v1 произвольные explicit Grok/Cursor homes не имеют доказанного home override и
остаются view-only даже при resume_context=native. Relocated-cwd bindings отклоняются
с ManualResumeGuide, кроме проверенного Codex 0.166.0 history_mode=paginated.

## SQLite reading

- URI mode=ro, query_only=ON, trusted_schema=OFF, disabled extensions, известные обычные
  таблицы и фиксированные параметризованные SELECT. SQL из sqlite_master не исполняется.
- Запрет native DDL/DML, checkpoint, VACUUM и repair. Native executable/SDK не используется
  для сканирования. Никакого immutable=1 на живом источнике.
- WAL учитывается. Нельзя создавать отсутствующий SHM/WAL при просмотре: если безопасное
  read-only открытие недоступно, источник получает unavailable.
- Bounded read transactions; busy/изменение источника — retry до двух раз, затем partial/stale.
- PRAGMA data_version сравнивается только в рамках одной открытой connection.
  Его значение не является глобальной revision между запусками.
- Несколько DB не образуют общую атомарную транзакцию. Paired fingerprints/cursors и
  согласованность thread/item references проверяются; результат имеет as_of range.
- При незавершённой JSONL строке живого append предыдущие строки доступны, хвост — partial.
  Нельзя считать такое чтение доказательством закрытости.

## Codex profile: 0.166.0 paginated

Пустой token_count.info допустим и не скрывает metadata. Ошибка history/usage одной
сессии ограничивается этой capability; предыдущая история сохраняется как partial.
Tool outputs в виде text-block arrays нормализуются в текст; non-text блоки явно
пропускаются с partial и без копирования opaque/image payload.

Metadata: state_5.sqlite threads; identity=id; cwd/title/preview/name/model;
created/updated/recency timestamps с предпочтением *_ms перед seconds; optional history_mode.
History: thread_history_1.sqlite tables:

| Таблица | Ключевые поля |
| ------- | ------------ |
| thread_turns | thread_id, turn_id, rollout_ordinal, status, started_at, completed_at, root_turn_id |
| thread_items | thread_id, turn_id, item_id, rollout_ordinal, item_json, item_type, created_at_ms, updated_at_ordinal |
| thread_realtime_items | thread_id, item_id, rollout_ordinal, created_at_ms, item_type, item_json |
| thread_history_projection_state | thread_id, next_rollout_byte_offset, next_rollout_ordinal |
| state_5.thread_spawn_edges | parent_thread_id, child_thread_id, status |

Сортировка по подтверждённому native ordinal/item_id, не по произвольному порядку SQLite.
В v1 текст берётся из thread_items/thread_realtime_items и rollout;
thread_turns/projection_state/spawn_edges перечислены как native schema evidence, а не
как отдельные сообщения. Turn IDs обычных items сохраняются. Изменение main/WAL/rollout
после metadata fingerprint делает результат partial; общей транзакции между DB нет.
Поддержанные ThreadItem: userMessage, agentMessage, commandExecution, fileChange,
mcpToolCall и другие whitelisted display types; internal/unknown payload не становится
обычным assistant message.

JSONL: session_meta, turn_context, response_item, event_msg, token_usage_record и compaction
metadata. Проекция и rollout одной native записи дают одно событие. Отсутствующий rollout
не скрывает доступную проекцию, но может ограничить history/resume/usage completeness.

Usage: payload.response_id + payload.thread_id; usage — per-response;
thread_token_usage/turn_token_usage — snapshots. Cached input/reasoning output являются
breakdown, не прибавкой к total. Legacy token_count snapshots — отдельный accounting scope.
Сброс legacy counters/compaction делает lifetime неполным. При смешении legacy snapshots
с receipts неизвестное перекрытие сохраняется как non_summable, не скрывается и не суммируется.
Если payload.thread_id отличается от ID файла-контейнера, расход не приписывается
контейнеру автоматически: ownership и membership должны следовать native evidence.

Resume argv: absolute_codex, resume, native_id, -C, cwd; проверенный CODEX_HOME context.
Нет --last, model override, fork или permission bypass.
Для установленного 0.166.0 history_mode=paginated отдельный rollout не обязателен,
но без него требуется сохранённый thread item в проверенной проекции. Один заголовок
без history items не даёт resume capability (history_not_recorded).
Этот профиль допускает новый существующий cwd при неизменных native ID/CODEX_HOME
и исходном history_locator; cold native resume проверен на offline искусственном store.
Если доступен только stale index без доказанно возобновляемого контекста, resume unavailable.

Mutation для этого paginated-профиля unavailable с reason=native_cascade_unbounded.
Native archive/delete и прямые изменения state/history DB не используются.
File-only legacy metadata/history может читаться при известной форме, но это не включает
непроверенные возможности cleanup для старых версий.

## Claude profile: native CLI 2.1.299 + проверенные JSONL shapes

Metadata/history: projects/<project>/<native-id>.jsonl.
Обязательная идентичность по sessionId/filename согласуется; cwd — из записей.
Model — последний непустой string message.model в assistant records; user metadata
не переопределяет модель. Это значение используется model filter/sort, не угадывается.
Не декодировать имя project directory как гарантированный cwd.
Root JSONL поддерживает user/assistant и whitelisted title/system/tool context.

uuid/parentUuid сохраняют историю ветвления. Повторные блоки одного message.id объединяются
только по известному stream/snapshot shape; assistant count не увеличивается на каждый chunk.
Tool_result-only user records — tool_result. Subagents входят в bundle корня и не выдаются
за самостоятельные возобновляемые корневые сессии без подтверждённой native семантики.

Usage: последнее корректное монотонное usage по message.id; регрессия/конфликт — partial.
Input = input_tokens + cache_read_input_tokens + cache_creation_input_tokens;
nested TTL breakdown не суммируется повторно. Fork memberships с тем же message.id
не дублируют факт в общей статистике.

Resume: absolute_claude, --resume, native_id; process cwd и доказанный config-root context.
Полный transcript path допустим только в проверенном native path-resume profile.
Никакого --continue, --fork-session, rm-background-runtime или project purge.

Cleanup manifest включает точный transcript и доказанно session-owned companions:
subagents/, tool-results/ и закрытые runs в workflows/. Script/run files остаются
неисполняемыми данными, внешние scriptPath не входят в bundle.
Официальная семантика per-session script/result storage: [Dynamic workflows](https://code.claude.com/docs/en/workflows#how-a-workflow-runs).
Project directory, shared history.jsonl, stats-cache.json и пользовательские файлы проекта
не входят. Неизвестные ссылки, sidechains/dependencies или права делают cleanup unavailable.

## Grok profile: Build 1.0.70

Root: <sessions>/<encoded-cwd>/<native-id>/, основной marker — summary.json.
Поля: info.id/info.cwd, created_at/updated_at/last_active_at, generated_title/session_summary,
current_model_id, chat_format_version. Images-only stub не становится session.

История: updates.jsonl ACP envelopes (timestamp, method, params.sessionId,
params.update, eventId/agentTimestampMs metadata). Chunk grouping по проверенным message/
prompt IDs. eventId — packet identity и сам по себе не разделяет сообщения; без
доказанного message/prompt ID соседние chunks объединяются с partial. params._meta
содержит eventId/agentTimestampMs/promptId. chat_history.jsonl — альтернативное представление, не второй независимый чат.
System/compaction материал не увеличивает user message count.

Usage: usage.json.session session totals единожды (старый плоский JSON также читается); turns/modelUsage — перекрывающиеся представления.
Недостающие поля, usageIsIncomplete/costIsPartial учитываются. signals contextTokensUsed
и contextWindowUsage не lifetime расход.

Resume: absolute_grok, --cwd, cwd, --resume, native_id. Никакого prompt, --session-id,
--restore-code, worktree/fork или bypass flags.
Native list/search/delete/export не используются для сканирования/уборки.
Неатрибутированный grok.db исключён из этого профиля.

Active registry: active_sessions.json; session_id/pid/pid_start/cwd/opened_at только как
evidence, с проверкой start identity/executable. Отсутствие записи не означает inactive.
Cleanup — весь доказанный локальный session bundle, включая нужные logs/snapshots,
без remote deletion. Неясная зависимость общего search/relocation metadata отключает mutation.

## Cursor profile: CLI 2026.10.22-27dcf5f

Root: ~/.cursor/chats/<workspace>/<chat-id>/, cwd из meta.json/проверенной metadata,
не из необратимого workspace hash. Store: blobs(id,data BLOB), meta(key,value TEXT), WAL.
meta['0'] — hex UTF-8 JSON; whitelisted agentId/latestRootBlobId/name/createdAt/lastUsedModel.
Нельзя сохранять или показывать blobEncryptionKey и другие неразрешённые свойства.

Проверенная read-only wire projection:
- ConversationStateStructure: field 8 — turn references;
- ConversationTurnStructure field 1 — AgentConversationTurnStructure;
- AgentConversationTurnStructure field 1 — user reference, field 2 — step references;
- UserMessage field 1 — text; optional field 18 — separate text reference;
- ConversationStep oneof различает assistant/tool/thinking; assistant field 1 — text.

Дескрипторы namespace-specific: одноимённый класс из другой области не используется.
Только достижимые nodes в порядке ссылок; visited set, отсутствие циклов, type checks.
Лимиты: blob <=32 МиБ, nesting <=64, varint <=10 bytes, <=100 000 nodes на сессию.
Превышение лимита/неизвестный codec — явная partial/unavailable история, не усечение без пометки.
Wire types 0/1/2/5 обрабатываются ограниченно; неподдержанные required shapes отклоняются.
Metadata JSON и protobuf projection проверяются синтетическими fixtures; неизвестные
JSON-encoded graph nodes/tool codecs остаются partial/unavailable. Vendor JS не импортируется.

Context usedTokens/maxTokens допустимы только с kind=context. Проверенный installed
descriptor 2026.10.22: ConversationStateStructure field 5 -> ConversationTokenDetails;
uint32 fields 1/2 -> used_tokens/max_tokens. Отсутствующее поле остаётся null, явный 0
сохраняется; malformed/unknown wire не даёт подставного нуля. ContextMetric содержит
source profile, root/source revision, observed_at и completeness. Отсутствие обоих
счётчиков оставляет context_metrics пустым; vendor JS и encryption keys не используются.
Cumulative input/output/total usage неизвестен без отдельного доказанного ledger.
Resume: absolute_cursor_agent, --workspace, cwd, --resume, native_id, process cwd=cwd.
Generic agent не подставляется; на исследованной машине он относится к Grok.

Cleanup — полный per-chat directory, включая coherent store/WAL и companions;
не global persistent-owner state и не .cursor/chats целиком. Lock presence валидируется;
отсутствие lock не означает inactive. Cursor IDE/ACP roots по умолчанию не сканируются.

## Минимальная матрица контрактных проверок

Для каждого reader: complete, absent, permission denied, truncated/corrupt, unknown schema,
missing ID/cwd/time/usage, alias/collision, changed-during-read, non-ASCII/control characters.
Дополнительно:
- Codex: missing rollout + available projection; cross-file generations; foreign thread
  attribution; repeated receipt/snapshot и bounded cleanup отказ.
- Claude: message chunks, tool-only user rows, forked message IDs, conflicting usage,
  shared project neighbors и неизвестные companion dependencies.
- Grok: ACP chunks, compaction alternative, usage totals vs turns/model, absent usage,
  stale/reused PID, local-only cleanup и посторонний grok.db.
- Cursor: reachable vs orphan blobs, protobuf/JSON, missing/cyclic/oversized nodes,
  secret-property exclusion, optional unknown fields, context-only metrics и WAL.

Fixtures создаются вручную/генератором из схем; копии реальных историй не используются.

## Cursor compatibility amendment — 2026-11-03

meta.json optional. Native SQLite meta identity=agentId должна совпадать с именем chat dir.
При отсутствии sidecar cwd восстанавливается только по единственному известному cwd
соседней сессии того же workspace, где MD5(cwd UTF-8) совпадает с именем workspace.
Без такого доказательства cwd остаётся unknown. Hash не обращается и пути не перебираются.
Binary references — 32-byte hashes с hex SQLite keys; legacy textual refs поддержаны.
ConversationTurnStructure agent.v1 различает agent field 1 и shell field 2;
shell command/stdout/stderr только отображаются. Unknown/missing node даёт partial,
но не прекращает чтение следующих turns/steps и не скрывает session metadata.
Opaque encrypted/model/key fields и reasoning не копируются.


## Phase 10 enumeration amendment — 2026-11-05

Missing/not-a-directory roots return partial/source_unavailable, including a fresh cache.
Known storage-directory enumeration errors return source_enumeration_failed instead of
complete empty; only verified absence of an optional child storage directory is empty.
JSONL projection is bounded to depth 64 / 100,000 nodes per record. An invalid/over-limit
record preserves its verified prefix and healthy neighbors as partial; diagnostics do
not include record contents. Unexpected worker exceptions isolate their root with
source_reader_failed; KeyboardInterrupt/SystemExit propagate. Checkpoint version changes
revalidate prior cached records from native sources without native writes.


## Codex archive metadata and closed WAL stores

Codex archived=0/1 is retained separately from manager hidden/presence; malformed values
make that record/root partial while healthy neighbors remain. Missing optional archived
columns disable native archive capabilities. Archive/unarchive capabilities are additive;
actual commit probes the real binary version and exact graph/history even when config
declares a version. The verified native mutation profile is paginated 0.166.0 only.

Codex readers may read a checkpointed WAL-mode main database with neither sidecar present
using an explicit closed_snapshot immutable read. The main fingerprint and continued
absence of sidecars are checked afterward. If WAL exists, normal read-only WAL semantics
apply; a missing companion is still an error. No sidecars/repair/checkpoints are created.
Other adapters keep the original strict default. Native archive additionally checks
ownership/containment and observed open handles before the native writer starts.


## Phase 12 size and timestamp observations — 2026-11-06

Full refresh also measures known history trees: Codex sessions/archived_sessions plus
state/history DB/WAL/SHM; Claude projects; Grok sessions plus named shared indices; Cursor
chats. Explicit narrow Grok/Cursor roots use the existing native marker shapes. No-follow
walks are bounded to depth 64 / 100,000 nodes and read stat data only. Symlink/denied/changed
artifacts yield partial/unknown size; optional absent layouts in an accessible root can
prove zero. This is a non-atomic observation, not per-session ownership or cleanup scope.
Metadata-only phases do not replace size observations. Failed refresh/mutations mark
previous evidence stale. File bodies, credentials and manager trash are excluded.
All adapters annotate naive timestamps as ambiguous without assigning a timezone;
missing and invalid timestamps have separate reasons. Known aware bounds are preserved.


## Phase 13 physical-location and no-follow amendment — 2026-11-06

Discovery retains every physical (root_id, locator) for a namespace/native ID, including
duplicates in one root. History/usage and worker transport keep per-location evidence
until content/cwd/graph agreement. Metadata alone does not prove agreement. Conflicting
copies suppress indexed content/usage and resume/cleanup; matching aliases share one
manager row, while cleanup still requires one location. Warm/reversed enumeration and
verified disappearance preserve the stable UID and hidden state.

Known-layout and fallback enumeration bind directory descriptors to the explicit root,
open each descendant with O_NOFOLLOW and compare device/inode before descent. Matched
links (including dangling links), denied parents and substituted directories give partial
enumeration/storage reasons, never complete empty zero. An explicitly configured root
alias remains valid; resolving an intermediate link does not authorize outside traversal.
Storage uses metadata only, retains inode dedup/as_of, and is not remeasured on stats open.


## Phase 14 reader/evidence amendment — 2026-11-06

Cursor's adapter-local decoded graph cache is keyed by physical locator; native agent ID
alone is not a cache key for different accepted locations. Native readers, scan maps and
IPC preserve the same per-copy distinction before identity agreement.

Usage agreement is independent of the history digest. Current-cycle normalized lifetime
facts/snapshots, ownership/scopes, counters and completeness must agree across aliases.
Pending, failed or conflicting peers yield explicit partial/unknown usage without hiding
agreed history. Different physical file stamps and context observation times are not
lifetime differences. Claude's within-stream monotonic receipt reconciliation remains;
disagreeing copies are not assumed newer by path or completion order.

Grok's proved eventId identifies a packet, separately from message/prompt IDs. Exact
replay is ignored before applying text deltas or tool status; different packets containing
the same text are retained. Conflicting payloads for one packet ID make history partial
and retain the first observation, without appending contradictory text. Supported-field
projection is shared with JSONL checkpoints; unknown properties are not persisted.
Normalizer 4 invalidates previous history/search/parser caches for these corrections.

## Phase 15 snapshot and activity boundary

Each NativeSQLite context pins schema, metadata and table/blob reads in one read
transaction. Live WAL commits may advance independently; the reader retains its coherent
snapshot. Main/WAL/SHM replacement or topology change causes source_changed on exit.
The closed immutable path still verifies the full main stamp and absent sidecars.
Separate Codex DBs retain fingerprint/as_of-range checks and never claim atomicity.
Cursor's cache fingerprint is observed before graph decoding, so a later commit forces
rediscovery. Normalizer 5 rebuilds prior history/search/parser caches with stable IDs.

Verified registry activity applies to every matching ID/cwd location, with PID birth
and executable checks unchanged. A stale registry row cannot replace positive evidence.
Alias publication carries current-cycle verified activity for the same identity/cwd
instead of losing it when selecting a representative. Prior-cycle or missing evidence
remains unknown during refresh; multi-location cleanup/archive stays unavailable.
