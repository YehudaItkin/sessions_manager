# Research: CLI-центр AI-сессий

**Date**: 2026-11-02
**Scope**: Phase 0 для [spec.md](spec.md). Исследованы локальные версии и структуры;
истории не запускались, не перемещались и не изменялись. В документ не включены тексты
разговоров, личные ID, ключи, счётчики реальных сессий или копии пользовательских данных.

## R1. Один локальный Python-пакет

**Decision**: Python >=3.12; Typer для команд, Textual для интерактивного обзора, Rich для
таблиц, tomli-w для корректной записи Warp TOML. Стандартные sqlite3, dataclasses, pathlib,
subprocess, zoneinfo и tomllib; без ORM, сервера, демона, AI SDK и сетевой синхронизации.
Публичная команда — `sessions`, имя пакета — `sessions-manager`, импорт — `sessions_manager`.

**Rationale**: JSONL, SQLite и локальные процессы не требуют серверного стека. Textual
предоставляет выбор строки, прокрутку, диалоги, фоновые workers и suspend. Команды используют
ту же прикладную логику. Exact dependency versions фиксируются в uv.lock при реализации;
сейчас зависимости не устанавливаются. Локально доступны Python 3.14.8, SQLite 3.53.4 и uv.

**Alternatives considered**: argparse/Rich потребовали бы собственной интерактивной UI-логики;
Rust/Go добавили бы стоимость разработки до доказательства проблемы производительности.
SQLAlchemy и динамический plugin framework не нужны для четырёх известных адаптеров.

Источники: [Typer](https://typer.tiangolo.com/tutorial/testing/),
[Textual](https://textual.textualize.io/guide/app/),
[tomli-w](https://github.com/hukkin/tomli-w),
[uv lock/sync](https://docs.astral.sh/uv/concepts/projects/sync/).

## R2. Независимые возможности источников

**Decision**: Версия CLI не заменяет проверку формата сохранённых данных. Адаптер проверяет
структуру, версию и источник каждого хранилища; возвращает независимые discover, history,
resume, usage и cleanup capabilities с причиной unavailable. Неизвестный формат не пустой
каталог и не успешная интеграция.

| Проверенный профиль | История и поиск | Возобновление | Расход токенов | Локальная уборка |
| ------------------ | -------------- | ------------- | -------------- | ---------------- |
| Codex CLI 0.166.0, paginated | Каталог + проекции + доступный JSONL; полнота отдельно | По ID при наличии возобновляемого контекста | Уникальные response receipts; snapshots отдельно | Отключена для этого профиля |
| Claude Code 2.1.299; наблюдавшиеся JSONL shapes 2.1.210/2.1.263 | JSONL и доказанно принадлежащие сессии companions | Точный ID в исходном cwd | Последняя корректная usage по message.id | Только проверенный изолированный закрытый bundle |
| Grok Build 1.0.70 | Нативные каталоги и ACP-события | Точный ID через установленный grok | usage.json; пропуски и неполнота явные | Только проверенный локальный закрытый bundle |
| Cursor CLI 2026.10.22-27dcf5f | Проверенный plaintext JSON/protobuf-граф | Точный ID через cursor-agent | Lifetime usage неизвестен; context occupancy отдельно | Только проверенный закрытый per-chat bundle |

**Rationale**: Это реализует FR-009/FR-016, не обещая произвольную совместимость.
Неподдержанная операция остаётся недоступной, а не считается реализованной заглушкой.
CLI может отсутствовать, хотя локальная история ещё читается.

**Alternatives considered**: Единый парсер для всех форматов, распознавание только по имени
каталога и универсальный recursive delete отвергнуты.

## R3. Codex: каталог и paginated-проекции обязательны

**Decision**: Учитывать CODEX_HOME, иначе `~/.codex`. Для проверенного профиля читать
`state_5.sqlite`: threads и thread_spawn_edges; `thread_history_1.sqlite`: thread_items,
thread_turns, thread_realtime_items, thread_history_projection_state; затем доступные
rollout JSONL. Родной ID — threads.id. Записи одного события из JSONL и проекций не дублируются.

**Rationale**: Локальная проверка показала индексированные разговоры с доступными проекциями,
но уже отсутствующим rollout. JSONL-only обнаружение потеряло бы их. Наличие строки каталога
не доказывает, что разговор полностью доступен или может быть продолжен.

**Alternatives considered**: Запуск app-server для каждого сканирования отвергнут: он не нужен
для чтения и может инициировать обслуживание состояния. Прямое изменение native SQLite запрещено.

Наблюдавшиеся структурные SHA-256, без хеширования пользовательских строк:
- threads + thread_spawn_edges: `7f5fe5236790d022d3f591bdc8317878192115cfe60902bca6688611b5bb1130`;
- четыре projection tables: `5c6ef9375ab498ac4de8f691575cd573e6ff173cbb4abccb729113968dd019ab`.

Схемы и курсоры перечислены в [контракте источников](contracts/sources.md).
Официальный контекст: [Codex CLI](https://learn.chatgpt.com/docs/codex/cli),
[App Server / thread lifecycle](https://learn.chatgpt.com/docs/app-server).
Конкретные схемы подтверждены установленной версией и read-only inspection.

## R4. Claude: история — граф, usage повторяется

**Decision**: Учитывать CLAUDE_CONFIG_DIR, иначе `~/.claude`; читать
`projects/<project>/<session-id>.jsonl`. Cwd берётся из записей, а не обратного декодирования
имени project directory. Сохранять uuid/parentUuid и порядок; tool_result-only user rows
не считаются пользовательскими сообщениями.

**Rationale**: Одна assistant message.id может встречаться в нескольких строках, а forks
повторяют старые сообщения. При монотонном обновлении берётся последняя корректная usage
этого API message; конфликт/регрессия делает метрику неполной.

**Alternatives considered**: Суммирование строк и смешение со stats-cache.json отвергнуты.
Нативный project purge не подходит для удаления отдельной сессии.

Источники: [CLI reference](https://code.claude.com/docs/en/cli-reference),
[Sessions](https://code.claude.com/docs/en/sessions),
[Local directory](https://code.claude.com/docs/en/claude-directory).

## R5. Grok Build: локальные файлы, не команды sessions list/delete

**Decision**: Читать `~/.grok/sessions/<encoded-cwd>/<session-id>/summary.json`,
`updates.jsonl`, при необходимости `chat_history.jsonl` как альтернативное представление,
и `usage.json`. Не считать images-only каталоги сессиями. Имена/cwd/даты брать из
поддержанных полей summary. ACP chunks группировать по event/message/prompt identity.

**Rationale**: Официальный Grok list/search может обращаться к удалённому реестру, а
sessions delete — удалять облачную копию или завершать живой runtime. Эти пути исключены
для локального сканирования и уборки. Найденный отдельно grok.db не доказан как формат
Grok Build 1.0.70 и в эту интеграцию не включён.

**Alternatives considered**: Парсинг CLI-вывода и импорт любой базы под .grok отвергнуты.
Нативный export не используется для фонового извлечения истории.

Источники: [Sessions](https://docs.x.ai/build/features/sessions),
[persistence.rs](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/session/persistence.rs),
[sessions_cmd.rs](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/src/sessions_cmd.rs),
[session_admin.rs](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/extensions/session_admin.rs).
Публичный commit и установленный build не тождественны: локальные shapes проверяются отдельно.

## R6. Cursor: ограниченный reader графа, без запуска vendor-кода

**Decision**: Читать только CLI `~/.cursor/chats/<workspace>/<chat-id>/store.db` и
meta.json. Meta key `0` — hex UTF-8 JSON; latestRootBlobId задаёт достижимый граф.
Поддержать только проверенную проекцию protobuf wire fields с ограничениями размеров,
глубины, varint, числа узлов, циклов и отсутствующих ссылок. Не выполнять установленный JS,
не использовать pickle и не извлекать encryption keys.

**Rationale**: Read-only probe подтвердил локальный plaintext-граф для установленного
профиля. Все blobs подряд не являются сообщениями: среди них старые ветви и служебные данные.
blobEncryptionKey не нужен проверенному reader и не попадает в каталог, UI или логи.
Unknown/encrypted codec оставляет метаданные, но делает историю/поиск недоступными.

**Alternatives considered**: Metadata-only недостаточен для проверенного читаемого формата;
выполнение runtime-модулей опасно из-за их инициализации и записей. Полноценный protobuf SDK
не требуется для небольшой фиксированной read-only wire projection; её формат и лимиты
фиксируются контрактными тестами.

Источники: установленный @anysphere/agent-cli-runtime и его namespace-specific descriptors;
[Cursor CLI](https://cursor.com/docs/cli/overview),
[CLI history](https://cursor.com/docs/cli/using),
[Protobuf encoding](https://protobuf.dev/programming-guides/encoding/).
Cursor ACP и IDE stores по умолчанию исключены: их resume-совместимость не доказана.

## R7. Токены: факты расхода, snapshots и полнота отдельно

**Decision**:
- Codex: `usage` по уникальному response_id; thread_id из payload определяет принадлежность.
  turn_token_usage/thread_token_usage не прибавляются. Cache/reasoning — подкатегории.
- Claude: уникальная message.id с последним корректным usage; нормализованный input =
  uncached input + cache-read input + cache-creation input. Total = input + output.
- Grok: итог session из usage.json берётся один раз; turns/modelUsage не добавляются
  повторно. total = input + output; usageIsIncomplete сохраняется.
- Cursor: context usedTokens не является lifetime расходом и не суммируется как таковой.

**Rationale**: Общий итог — объединение доказанно уникальных фактов, а не сумма
пересекающихся session totals. Факт может входить в несколько histories. Snapshots без
доказательства независимого accounting scope не объявляются аддитивными. Неизвестное
значение остаётся null с причиной и покрытием, известный ноль — 0.

**Alternatives considered**: Оценка токенизацией текста, смешение context occupancy с расходом
и расчёт денег по текущим тарифам отвергнуты.

Источники: [Anthropic cache accounting](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
[Grok usage file](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/session/usage_file.rs),
[Grok usage ledger](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-chat-state/src/usage.rs),
локальные Codex protocol schemas и записи только по структуре.

## R8. Приватный SQLite-каталог и точная Unicode-подстрока

**Decision**: Собственный SQLite-каталог и внешнее content-table FTS5 trigram.
Нормализация текста и запроса — str.casefold() без удаления диакритики; версия Unicode
входит в версию индекса. FTS — только ускоритель кандидатов: окончательный критерий
`instr(folded_text, folded_query) > 0`. Запросы короче трёх code points используют точный
scan по отфильтрованной выборке. MATCH получает escaped literal, а не язык запросов пользователя.

**Rationale**: Словарный FTS не равен поиску подстроки, SQLite NOCASE не даёт нужной Unicode
семантики, а LIKE трактует %/_ как шаблоны. Проверка на искусственных строках подтвердила
кириллицу, Straße/STRASSE, буквальные %/_, короткий символ и часть английского слова.
Это проверка корректности, а не доказательство SC-002.

**Alternatives considered**: Elasticsearch/другой сервер избыточен; prefix-only MATCH нарушает FR-006.
Невозможность создать FTS5 trigram определяется startup probe с понятным отказом/doctor,
без загрузки сторонних расширений в чужие базы.

Источники: [FTS5 trigram](https://sqlite.org/fts5.html#the_trigram_tokenizer),
[Python casefold](https://docs.python.org/3.12/library/stdtypes.html#str.casefold).

## R9. Чтение SQLite и согласованность

**Decision**: Native DB открываются URI mode=ro + query_only; короткие read transactions.
WAL учитывается, checkpoint/VACUUM/DDL на источнике запрещены. immutable=1 не применяется
к живой базе. Если открытие потребовало бы создания sidecars, чтение прекращается с причиной;
никакого repair. Для нескольких DB — paired fingerprints/cursors, bounded retry и stale/partial,
поскольку межфайлового атомарного snapshot здесь нет.

**Rationale**: WAL — часть состояния. Режим immutable отключает проверки изменения.
Read locks в существующем SHM не выдаются за изменение логической истории; источники
не получают новых записей. Реальные backups для cleanup делаются только при подтверждённом
покое, а не копированием одного main DB без WAL.

**Alternatives considered**: Копировать только .sqlite или объявить живую базу immutable небезопасно.
Источники: [SQLite WAL](https://sqlite.org/wal.html),
[SQLite URI](https://sqlite.org/uri.html), [Python sqlite3](https://docs.python.org/3.12/library/sqlite3.html).

## R10. Корзина: только доказанно локальная и ограниченная операция

**Decision**: Скрытие всегда меняет только менеджер. Codex paginated cleanup отключена:
archive/delete каскадируют на descendants, а установленный протокол не принимает expected
revision, confirmed closure или nonrecursive flag. Прямой DML в native shared DB запрещён.

Для остальных профилей cleanup включается только после проверки полного session-owned
bundle, согласованной backup-копии, отсутствия известных писателей и условий закрытости.
Unknown activity требует отдельного утверждения пользователя; это не отменяет обнаруженный
writer или неподдержанный формат. Same-device перемещения выполняются без перезаписи,
с durable journal и fsync; межтомовое удаление в первом профиле недоступно.
Восстановление использует no-replace, не exists()+replace. Whole shared-DB rollback запрещён.

**Rationale**: rename не останавливает процесс с открытым FD; lock менеджера не управляет
нативными писателями. Операции гарантируют сохранность при соблюдении явно подтверждённых
условий закрытости и отказывают при обнаруженном изменении. Нельзя обещать необусловленную
атомарность между файлами и каталогом.

**Alternatives considered**: Native purge, generic rmtree и восстановление всей базы отвергнуты.
На macOS проверены наличие renameatx_np и RENAME_EXCL в SDK; отсутствие поддержки томом
делает mutation недоступной. Детальный протокол — [cleanup contract](contracts/cleanup.md).

## R11. Продолжение в терминале и Warp

**Decision**: Абсолютные executable paths, argv и cwd; shell=False. В Textual —
App.suspend(), foreground child с inherited stdio, восстановление UI и refresh после выхода.
Cursor использует cursor-agent: generic agent здесь принадлежит другой установке.

Уточнение владельца 2026-11-02: history_locator исходной сессии отделён от нового cwd.
Продолжение в другой папке допускается только при подтверждённой native binding; иначе
вместе показываются причина, выбор другой папки/отмена и инструкция ручного запуска.
Непроверенный рецепт не генерируется и инструкция не выполняется автоматически.

Warp получает manager-owned Tab Config TOML и warp://tab_config/<generated-name>.
Команда конфигурации содержит только доверенный launcher менеджера, private data-dir
и случайный одноразовый ticket; исходный ID, cwd, title и transcript в shell/URI не подставляются.
Private manifest передаёт argv/cwd helper-у, который повторно проверяет их и запускает без shell.
Статусы доставки URI, запуска процесса и загрузки родной сессии не смешиваются.

**Rationale**: Обычный new_tab URI не исполняет команды. Tab Config — документированный путь.
Установленная Warp 0.2026.10.21.08.25.02 содержит поддержку этой возможности; фактический
handoff проверяется искусственным launcher-ом на этапе реализации.

**Alternatives considered**: Выдуманный command= URI и ввод команд через UI automation отвергнуты.
Источники: [Warp URI](https://docs.warp.dev/terminal/more-features/uri-scheme),
[Tab Configs](https://docs.warp.dev/terminal/windows/tab-configs/),
[Textual suspend](https://textual.textualize.io/api/app/#textual.app.App.suspend),
[Python subprocess](https://docs.python.org/3.12/library/subprocess.html).
Ни одна реальная сессия при исследовании не открывалась.

## R12. Проверки и завершение исследования

**Decision**: pytest + pytest-asyncio, Typer CliRunner, Textual Pilot, искусственные native
stores, fault injection после каждой границы journal/fsync/rename, отдельный performance gate
на 10 000 сессий / 1 ГиБ. Тесты поведения пишутся и падают до реализации.
Ruff используется только как dev dependency для lint/format; он не заменяет поведенческие тесты.
Источники: [Textual testing](https://textual.textualize.io/guide/testing/),
[pytest tmp_path](https://docs.pytest.org/en/stable/how-to/tmp_path.html),
[Ruff](https://docs.astral.sh/ruff/).

**Rationale**: Требуются проверки реальных границ: WAL, partial history, forks, отсутствующие
метрики, активность, terminal control characters, replay, restore collision и соседние сессии.
Личная история не становится фикстурой. Временные research probes не являются приложением.

**Alternatives considered**: Только mocks без native-shape fixtures и только happy-path
проверки не подтверждают безопасность. Формальное покрытие строк не заменяет сценарии.

Все вопросы Technical Context получили решения R1–R12. Продуктовых уточнений не осталось.
Оставшиеся fixture/runtime/performance проверки — обязательные gates реализации, а не
заявление, что приложение, безопасная mutation или производительность уже подтверждены.
