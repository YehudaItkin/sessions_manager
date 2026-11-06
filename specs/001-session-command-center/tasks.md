---
description: "Dependency-ordered implementation tasks for the Sessions Manager CLI command center"
---

# Tasks: Единый CLI-центр AI-сессий

**Input**: Design documents from `specs/001-session-command-center/`
**Branch**: `001-session-command-center`
**Created**: 2026-11-02
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [CLI](contracts/cli.md), [sources](contracts/sources.md),
[launch](contracts/launch.md), [cleanup](contracts/cleanup.md), [quickstart](quickstart.md).
**Tests**: Обязательны по запросу владельца, конституции и FR-027; используется TDD.
**Organization**: Setup → foundations → пять пользовательских сценариев по приоритету → polish.
Статус реализации и проверки отражён checkbox каждой задачи; evidence — в validation.md.

## Format: `[ID] [P?] [Story] Description`

- Каждая задача имеет checkbox, последовательный T-ID и точные project-relative file paths.
- [P] означает готовую независимую файловую работу внутри указанной волны, не разрешение
  игнорировать dependencies/phase barriers. Это не поручение автоматически запускать агентов.
- [US1]–[US5] есть только у задач пользовательских фаз; setup/foundation/polish не имеют story label.
- Блок Tests пишется и запускается до соответствующего production behavior. В implementation
  входят только минимальные изменения для green и последующий refactor с passing tests.
- Red должен относиться к ожидаемому новому поведению, а не сломанному окружению или
  невалидной фикстуре. Уже работающий negative/safety case не требуется искусственно ломать.
- Общие models/catalog/cli/ui и provider files редактируются только в порядке зависимостей.
  Параллельная волна заканчивается перед переходом Tests → Implementation.

## Path Conventions

Один пакет: `src/sessions_manager/`; тесты: `tests/unit/`, `tests/contract/`,
`tests/integration/`, `tests/acceptance/`, `tests/performance/`;
генераторы/harmless children: `tests/support/`. Все пути ниже от repository root.
Private data-dir, generated corpora и native histories находятся за пределами репозитория.
Фразы «Модель: …» цитируют field/validation constraints из data-model.md; они обязательны.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Создать пакет, locked окружение и изолированный test harness. Ни истории владельца, ни исходные CLI не используются как test inputs.

- [X] T001 Инициализировать Python >=3.12 пакет sessions-manager и console entry sessions; зафиксировать runtime/dev зависимости через uv. Файл: `pyproject.toml`.
  Также: `uv.lock`, `src/sessions_manager/__init__.py`.
  Зависимости: нет.
  Typer, Textual, Rich, tomli-w; pytest, pytest-asyncio и Ruff в dev group. Создать только package
  scaffold, без бизнес-логики; поддержать uv sync --locked --group dev.

- [X] T002 [P] Исключить окружение, generated corpora, приватные runtime данные и отчёты тестов из Git. Файл: `.gitignore`.
  Зависимости: нет.
  Не исключать synthetic fixture seeds или uv.lock; не менять существующие tracked Spec Kit templates.

- [X] T003 [P] Настроить изоляцию тестов, временные roots, сетевой запрет и явные opt-in параметры. Файл: `tests/conftest.py`.
  Также: `tests/support/__init__.py`, `tests/support/fake_cli.py`.
  Зависимости: T001.
  Зарегистрировать --run-warp и --corpus; fixture config использует discovery_roots_mode=replace. Не
  переопределять HOME и не читать production histories; harmless fake children вместо AI CLI. Общий
  harmless child пишет только synthetic argv/cwd/ack в свой fixture root; не читает credentials и не
  требует production CLI.

**Checkpoint**: Scaffold и test harness готовы; runtime behavior ещё не считается реализованным.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Общие модели, приватные данные, native read-only boundary, catalog и CLI plumbing. Это блокирует все пользовательские сценарии.

**Blocking gate**: Setup завершён; foundations полностью завершаются до US1.

### Tests (обязательный TDD / RED)

- [X] T004 [P] Написать и запустить падающие проверки общих value types, identities, capabilities и generations. Файл: `tests/unit/test_models.py`.
  Зависимости: T001, T002, T003.
  Проверить enums/null/UTC/integer-vs-bool, stable ID через refresh/root move, aliases, конфликт
  одинаковой identity, persistent hide tombstone и отсутствие права resume у surrogate.

- [X] T005 [P] Написать и запустить падающие проверки config, namespace roots, приватности data-dir и безопасных diagnostics. Файл: `tests/unit/test_config.py`.
  Зависимости: T001, T002, T003.
  Проверить standard roots, explicit replacements, view-only custom roots, owner/mode rejection без
  chmod чужих каталогов, отсутствие credentials в persisted context и логах.

- [X] T006 [P] Написать и запустить падающие проверки read-only native SQLite boundary. Файл: `tests/integration/test_native_sqlite.py`.
  Зависимости: T001, T002, T003.
  Реальный synthetic WAL, missing sidecars, busy/read retries, malicious view/schema,
  query_only/trusted_schema, запрет DDL/DML/repair/checkpoint/immutable на live source; исходные
  main/WAL bytes не меняются.

- [X] T007 [P] Написать и запустить падающие проверки version/shape profiles и отказа неподдержанной возможности. Файл: `tests/contract/test_source_profile.py`.
  Зависимости: T001, T002, T003.
  Состояния discover/history/resume/usage/cleanup независимы; CLI version не заменяет schema
  predicate. Unknown format — unavailable с причиной, а не пустой успешный source.

- [X] T008 [P] Написать и запустить падающие проверки собственного catalog и миграций. Файл: `tests/integration/test_catalog.py`.
  Зависимости: T001, T002, T003.
  Проверить foreign keys, уникальность namespace/native_id, parameter binding, атомарную session
  generation, один writer/read connections и отсутствие native-schema migrations.

- [X] T009 [P] Написать и запустить падающие проверки глобального CLI-контракта, help/version и error envelope. Файл: `tests/contract/test_cli_common.py`.
  Зависимости: T001, T002, T003.
  contracts/cli.md: --config/--data-dir/--format, schema_version=1, stdout JSON/stderr safe
  diagnostics и exit codes 0/1/2/3/4/5/6/7/8/130. Help/version не сканируют roots.

### Implementation (после соответствующего RED)

- [X] T010 Реализовать общие модели SourceRoot, Session, SessionLocation, Project, ActivityEvidence и ScanGeneration. Файл: `src/sessions_manager/models.py`.
  Зависимости: T004.
  Включить все поля data-model.md §1–3, typed validation, schema/generation provenance;
  normalizer_version учитывает Unicode version. Native account tokens не нужны для namespace.
  Модель: «Все ID — строки с типом/namespace; пользовательский ID не является номером строки.».
  Модель: «Время: UTC epoch milliseconds либо null, плюс provenance и timezone-confidence.».
  Модель: «Счётчики: неотрицательный integer либо null; bool не принимается как число.».
  Модель: «Полнота: complete / partial / unavailable / stale с причиной и as_of.».
  Модель: «Возможность действия: supported / unavailable / unsafe с machine-readable reason.».
  Модель: «Native paths — абсолютные; нормализация пути не заменяет проверку владельца, symlinks и
  допустимой области операции.».
  Модель: «Стабильный UUID локальной конфигурации».
  Модель: «codex / claude / cursor / grok».
  Модель: «Логический профиль одного источника, не путь и не прочитанный account token».
  Модель: «Native home или явно добавленное history location».
  Модель: «Проверенный формат, независимо от версии executable».
  Модель: «Разрешённый native CLI либо null».
  Модель: «Доказанная связь этого расположения с native CLI; иначе view-only».
  Модель: «Детерминированный полный UUID от namespace + native_id».
  Модель: «Стабильный полный человекочитаемый handle; краткая форма только при уникальности».
  Модель: «Составная уникальная принадлежность».
  Модель: «Только whitelisted значения; null допустим».
  Модель: «Постоянный manager-only признак».
  Модель: «present / source_unavailable / missing / trashed / purged».
  Модель: «active / inactive / unknown и ссылка на ActivityEvidence».
  Модель: «Независимые metadata/history/search/resume/usage/cleanup с причинами».
  Модель: «preferred/alias/conflict status».
  Модель: «state (running / complete / partial / failed / cancelled)».
  Модель: «При отсутствии native_id назначается постоянный surrogate по проверенной identity
  артефакта; наличие surrogate не разрешает resume/delete без доказанной связи.».
  Модель: «Тот же native_id разных providers/namespaces не смешивается.».
  Модель: «Совпадающие aliases не дублируют строку.».
  Модель: «Несовместимые содержимые с одной identity дают identity_conflict; не выбирается случайная
  копия, а опасные действия отключаются.».
  Модель: «Fingerprint для инвалидации включает dev/inode/size/mtime_ns и native revision/cursor; это
  не доказательство inactivity.».
  Модель: «Cwd берётся из native metadata, не угадывается из encoded directory name.».
  Модель: «Визуальное сокращение ID не меняет его значения; show и JSON содержат полные ID.».

- [X] T011 [P] Реализовать приватные пути/config, root namespaces и безопасные diagnostic results. Файл: `src/sessions_manager/config.py`.
  Зависимости: T010, T005.
  Default user Application Support, config.toml, catalog.sqlite3, trash/launches; code/repository cwd
  не используются для runtime state. Persist только явный config и allowlisted native-home context.
  Модель: «Новые директории 0700, файлы/DB/WAL/SHM 0600, umask 077; существующий чужой/небезопасный
  data-dir вызывает отказ без автоматического chmod пользовательских каталогов.».
  Модель: «Diagnostics содержат коды и агрегаты, не содержимое событий или секреты.».
  Модель: «Перемещение корня не меняет namespace.».
  Модель: «Добавление произвольной копии не даёт права продолжать её через другой native home.».

- [X] T012 [P] Реализовать ограниченный reader native SQLite без source mutation. Файл: `src/sessions_manager/sources/sqlite_reader.py`.
  Зависимости: T010, T006.
  URI mode=ro, query_only=ON, trusted_schema=OFF, disabled extensions и table/type whitelist; короткие
  snapshots, WAL, максимум два retry; никаких новых sidecars или immutable. data_version сравнивать в
  той же connection, paired DB имеют as_of range.

- [X] T013 [P] Реализовать общий typed source contract и registry совместимости. Файл: `src/sessions_manager/sources/base.py`.
  Зависимости: T010, T007.
  Из contracts/sources.md: probe/discover, capability/reason и source revisions; story-specific
  интерфейсы добавляются по мере реализации. Не объявлять неподдержанные функции успешно
  реализованными.

- [X] T014 Реализовать приватный catalog, базовую схему и собственные миграции. Файл: `src/sessions_manager/catalog.py`.
  Зависимости: T010, T011, T008.
  Persist roots/sessions/locations/projects/activity/generations; один writer, separate readers,
  FK/unique constraints и атомарная публикация. Failure корня не mass deletion; retain identity/hide
  tombstones.
  Модель: «Каталог SQLite использует один writer и отдельные read connections для workers/UI.».
  Модель: «Foreign keys, параметризованные запросы и явные транзакции обязательны.».
  Модель: «Миграции только собственного каталога; native schemas никогда не мигрируются менеджером.».

- [X] T015 Реализовать entrypoint, глобальные опции, JSON envelope и безопасную обработку ошибок. Файл: `src/sessions_manager/cli.py`.
  Также: `src/sessions_manager/__main__.py`.
  Зависимости: T011, T014, T013, T009.
  Подключить Typer без eager scanning на import/help/version; общий renderer/error mapping и lazy
  entry для последующего overview. Не добавлять фиктивные успешные команды отсутствующего поведения.

**Checkpoint**: Typed foundation, приватность, source boundary и собственные migrations проходят соответствующие тесты; можно начинать US1.

---

## Phase 3: User Story 1 - Сразу увидеть свои сессии (Priority: P1) — MVP

**Goal**: Один no-argument overview четырёх локальных источников с устойчивыми ID, metadata, activity/capabilities и честными health/partial состояниями.

**Independent Test**: Изолированный corpus четырёх providers: один запуск показывает ожидаемые сессии без дублей; unreadable source не скрывает здоровые, отсутствие CLI не скрывает читаемую историю. Смена порядка/refresh сохраняет IDs, пустое состояние объясняет проверенные roots.

**Traceability**: FR-001–FR-005, FR-008–FR-009, FR-026; SC-001, ранний SC-002, SC-008; US1 scenarios 1–4.

### Tests for User Story 1 (обязательный TDD / RED)

- [X] T016 [P] [US1] Написать и запустить падающие metadata/discovery contract tests Codex. Файл: `tests/contract/test_codex_metadata.py`.
  Также: `tests/support/codex_factory.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  Synthetic 0.166.0 state_5/thread_history_1 + JSONL; metadata без rollout, missing projection,
  ms/seconds, unknown shape, denied root. Codex paginated cleanup всегда
  unavailable/native_cascade_unbounded.

- [X] T017 [P] [US1] Написать и запустить падающие metadata/discovery contract tests Claude. Файл: `tests/contract/test_claude_metadata.py`.
  Также: `tests/support/claude_factory.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  Synthetic projects/<project>/<id>.jsonl и companions; source cwd/title/time из записей, не folder
  decoding; duplicate IDs, отсутствующий CLI, неизвестный record shape и shared neighbors.

- [X] T018 [P] [US1] Написать и запустить падающие metadata/discovery contract tests Grok. Файл: `tests/contract/test_grok_metadata.py`.
  Также: `tests/support/grok_factory.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  Synthetic 1.0.70 summary/info.id/cwd/source dates; images-only stub не session; сторонний grok.db
  исключён; ни list/search/export, ни cloud/native delete не вызываются.

- [X] T019 [P] [US1] Написать и запустить падающие metadata/discovery contract tests Cursor. Файл: `tests/contract/test_cursor_metadata.py`.
  Также: `tests/support/cursor_factory.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  Synthetic per-chat meta.json/store.db с hex meta['0']; whitelisted metadata, malformed
  hex/WAL/unknown version; blobEncryptionKey не сохраняется/выводится; IDE/ACP не импортируются как
  CLI.

- [X] T020 [P] [US1] Написать и запустить падающие проверки scan coordinator, roots и generation reconciliation. Файл: `tests/integration/test_discovery.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  Fake typed adapters + real manager catalog: standard/custom roots, aliases/conflicts, stable IDs,
  deleted vs unreadable root, bounded concurrency, cancelled/incomplete scans, cached-as-of status;
  FR-002–FR-005/009/026.
  Проверить full refresh выбранных roots при project/date фильтре A: сессия B вне фильтра
  обновляется и не становится missing; невыбранный root C сохраняет records/generation/as_of.

- [X] T021 [P] [US1] Написать и запустить падающие проверки положительной activity evidence. Файл: `tests/unit/test_activity.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  PID reuse/start identity/executable mismatch, stale/missing locks/registry, known writer и unknown;
  timestamp не равен работающему процессу, source не завершается.

- [X] T022 [P] [US1] Написать и запустить падающие CLI/TUI acceptance tests первого обзора. Файл: `tests/contract/test_overview_cli.py`.
  Также: `tests/acceptance/test_overview.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  Seed catalog synthetic records: no-arg TTY vs redirected list, 4 источника, пустое состояние,
  last-activity sorting/unknown-last, health/capabilities, стабильный выбор при refresh. JSON list
  fields и exit=3 при partial; US1 scenarios 1–4.
  Строка различает display_id/native_id; narrow terminal сокращает длинные значения с явным
  признаком, JSON сохраняет оба полностью, усечённый native ID не становится selector/argv.
  Коллизия коротких manager handles требует длинного префикса/полного ID, не выбора другой сессии.

- [X] T023 [P] [US1] Написать и запустить падающие проверки synthetic corpus utility и раннего discovery budget. Файл: `tests/unit/test_corpus.py`.
  Также: `tests/performance/test_discovery_budget.py`.
  Зависимости: T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
  --output/--profile mixed/--sessions/--history-bytes, fixture.toml roots_mode=replace, expected IDs и
  harmless CLI bindings. Измерять cold enumeration <=10 с / warm overview <=2 с; ещё не выдавать это
  за полный search SC-002.

### Implementation for User Story 1 (после соответствующего RED)

- [X] T024 [P] [US1] Реализовать Codex profile, metadata discovery и per-record capabilities. Файл: `src/sessions_manager/sources/codex.py`.
  Зависимости: T016, T013, T012.
  Контракт sources.md: CODEX_HOME, threads/edges, paginated projection availability и JSONL locators;
  источники времени явно. Отсутствующий rollout не теряет доступную строку; stale index не обещает
  resume. Native app-server/DB writes не используются.

- [X] T025 [P] [US1] Реализовать Claude profile и metadata discovery. Файл: `src/sessions_manager/sources/claude.py`.
  Зависимости: T017, T013.
  CLAUDE_CONFIG_DIR, observed JSONL shapes, native cwd/title/dates, root sessions vs owned subagents;
  shared project state не отдельная сессия. Unknown formats и resume-context ambiguity явные.

- [X] T026 [P] [US1] Реализовать Grok Build profile и direct local metadata discovery. Файл: `src/sessions_manager/sources/grok.py`.
  Зависимости: T018, T013.
  Summary-backed session dirs, standard/custom roots, native timestamps, active registry evidence без
  вывода содержимого; ни scanning всего home, ни вызов sessions list/search/delete.

- [X] T027 [P] [US1] Реализовать Cursor CLI profile и metadata reader. Файл: `src/sessions_manager/sources/cursor.py`.
  Зависимости: T019, T013, T012.
  Per-chat store/meta.json, hex JSON whitelist, latestRootBlobId как locator; без выполнения JS и без
  копирования secret properties. Cumulative usage unknown, history capability пока включается только
  после US2 tests.

- [X] T028 [P] [US1] Реализовать проверку activity evidence без ложного inactive. Файл: `src/sessions_manager/activity.py`.
  Зависимости: T021, T010.
  Сверять native PID/start/executable/context и известные writers; не запрашивать новые права и не
  подавать signals остановки.
  Модель: «Только положительная проверенная связь записи с живым процессом даёт active.».
  Модель: «Отсутствие процесса/lock не доказывает отсутствие другого runtime: обычно unknown.».
  Модель: «PID reuse и устаревшая запись не дают положительного статуса.».

- [X] T029 [P] [US1] Реализовать генератор изолированного смешанного native corpus для quickstart/performance. Файл: `tests/support/make_corpus.py`.
  Зависимости: T023, T016, T017, T018, T019.
  Использовать независимые synthetic factories, фиксированный seed, expected.json, fixture.toml с
  production roots disabled и fake CLI bindings. Уметь 40 небольших сессий и 10 000/1 ГиБ; генерация
  не включается во время приложения.

- [X] T030 [US1] Реализовать bounded discovery coordinator и атомарное обновление catalog. Файл: `src/sessions_manager/discovery.py`.
  Также: `src/sessions_manager/catalog.py`.
  Зависимости: T024, T025, T026, T027, T028, T020.
  Объединять roots без дублей, сохранять identity/hide state, сортировать known timestamps, ограничить
  workers/один writer; cancel/failure не превращать в complete empty.
  Источники выбираются --source/активным source filter; каждый выбранный root перечисляется
  полностью. Project/date filters применяются только к выводу. Missing reconciliation
  разрешена лишь после полного успешного scan соответствующего root, не выбранной страницы.
  Модель: «Публикация одной законченной session generation атомарна в собственном каталоге.».
  Модель: «Полная удачная enumeration может пометить исчезнувшие записи missing; ошибка корня — только
  stale/source_unavailable, не mass deletion.».
  Модель: «Фильтры проекта и даты ограничивают только вывод, не enumeration/reconciliation.».

- [X] T031 [US1] Реализовать no-arg terminal overview, source status и refresh. Файл: `src/sessions_manager/ui/app.py`.
  Также: `src/sessions_manager/ui/screens.py`.
  Зависимости: T030, T022.
  display_id/native_id/provider/title/project/last activity/current activity/доступные действия;
  оба ID обозначены раздельно, сокращение лишь визуальное; progress/stale/empty
  состояния, selection по ID и hidden/trash counts. Не рекламировать ещё не реализованные story
  actions как работающие.

- [X] T032 [US1] Подключить no-arg routing и list/refresh/sources/doctor к рабочему overview. Файл: `src/sessions_manager/cli.py`.
  Зависимости: T031, T030, T029, T022.
  TTY открывает UI; redirected invocation не ждёт input. Пагинация list default 50/offset 0, global
  JSON envelope, sources add namespace/view-only config, doctor без credentials; green contract/US1
  tests.
  Raw IDs в JSON полные; --source ограничивает обновляемые источники, project/date не
  ограничивают enumeration и не стирают записи вне фильтра.

**Checkpoint**: Полезный MVP: общий metadata overview, no-arg TUI/non-TTY list, источники и refresh. Поиск, resume, cleanup и stats ещё не объявляются готовыми.

---

## Phase 4: User Story 2 - Найти сессию и понять, что в ней делали (Priority: P1)

**Goal**: Найти сессию по metadata/содержимому, фильтрам и датам; безопасно просмотреть доступную нормализованную историю.

**Independent Test**: Поиск фрагмента внутри сообщения выбирает правильную сессию; UI/CLI показывают именно её graph/порядок, metadata/provenance и страницы. Casefold/literal %/_/короткие запросы, обе границы дат, missing fields и hostile terminal content дают ожидаемый результат.

**Traceability**: FR-004, FR-006–FR-007, FR-024–FR-026; SC-002, SC-003, SC-007; US2 scenarios 1–7.

### Tests for User Story 2 (обязательный TDD / RED)

- [X] T033 [P] [US2] Написать и запустить падающие проверки history/events/membership и generation-aware search storage. Файл: `tests/unit/test_history_models.py`.
  Также: `tests/integration/test_history_catalog.py`.
  Зависимости: T032.
  Проверить role enums, ordering/branch membership, missing/partial vs empty, event dedup, secret
  property exclusion и атомарную публикацию нового индекса с инвалидацией старого.

- [X] T034 [P] [US2] Написать и запустить падающие Codex history contracts на проекции и rollout. Файл: `tests/contract/test_codex_history.py`.
  Также: `tests/support/codex_factory.py`.
  Зависимости: T032.
  thread_items/turns/realtime/projection cursor, stable order, missing rollout + surviving projection,
  no double display, pair changes/busy, unknown items и bounded pages; fixture records синтетические.

- [X] T035 [P] [US2] Написать и запустить падающие Claude graph/chunk history contracts. Файл: `tests/contract/test_claude_history.py`.
  Также: `tests/support/claude_factory.py`.
  Зависимости: T032.
  uuid/parentUuid, user string/blocks, assistant chunks, tool_result-only user rows, copied/forked
  history и subagents без неверного root resume; неполная структура маркируется.

- [X] T036 [P] [US2] Написать и запустить падающие Grok ACP reconstruction contracts. Файл: `tests/contract/test_grok_history.py`.
  Также: `tests/support/grok_factory.py`.
  Зависимости: T032.
  updates.jsonl event/message/prompt grouping, trailing incomplete line, chat_history alternative,
  compaction/system events и неизвестный chat_format_version; remote commands не вызываются.

- [X] T037 [P] [US2] Написать и запустить падающие Cursor wire/graph history contracts. Файл: `tests/contract/test_cursor_history.py`.
  Также: `tests/unit/test_cursor_wire.py`, `tests/support/cursor_factory.py`.
  Зависимости: T032.
  Namespace-specific protobuf/JSON, reachable vs orphan nodes, missing/cyclic/oversized blobs,
  varint/type/UTF-8 limits, optional fields, unsupported/encrypted codec и отсутствие encryption key в
  результате.

- [X] T038 [P] [US2] Написать и запустить падающие literal-search и date/selection tests. Файл: `tests/unit/test_search.py`.
  Также: `tests/integration/test_search_index.py`.
  Зависимости: T032.
  Casefold кириллица/ß, literal %/_, quotes и 1–2 codepoints, crossing physical page boundary,
  inclusive dates/DST ambiguity, AND filters/OR sources, unknown-last both sorts, stable IDs и
  stale/cancelled completeness.
  Применённый project/date filter меняет только результат вывода после полного refresh
  выбранных roots; B вне фильтра сохраняется и обновляется, невыбранные roots не затрагиваются.

- [X] T039 [P] [US2] Написать и запустить падающие show/search CLI и history UI acceptance tests. Файл: `tests/contract/test_history_commands.py`.
  Также: `tests/acceptance/test_history.py`.
  Зависимости: T032.
  US2 scenarios 1–7: query только внутри сообщения, все metadata/provenance/capabilities, pages=100,
  filters/reset, terminal ANSI/OSC/Rich/bidi payload остаётся данными; source failures не блокируют
  здоровые.
  Show возвращает полные display_id/native_id после визуального сокращения в списке;
  filtered refresh не делает невидимые сессии missing.

- [X] T040 [P] [US2] Написать full-readiness performance gate для нового процесса, TUI, history и literal search. Файл: `tests/performance/test_overview_budget.py`.
  Зависимости: T032, T029.
  На --corpus 10 000/1 ГиБ: cold discovery+search readiness <=10 с, warm meaningful
  overview/search/navigation <=2 с; включая short queries. Partial результат не считается полным,
  environment/seed записываются.

### Implementation for User Story 2 (после соответствующего RED)

- [X] T041 [US2] Добавить нормализованные HistoryEvent/membership/SearchChunk и собственные migrations. Файл: `src/sessions_manager/models.py`.
  Также: `src/sessions_manager/catalog.py`, `src/sessions_manager/sources/base.py`.
  Зависимости: T033.
  Все поля data-model.md §3, typed history reader contract, per-session graph membership и
  reader/normalizer provenance; новые таблицы только manager-owned.
  Модель: «(user / assistant / tool_call / tool_result / system / unsupported)».
  Модель: «Сохраняются порядок и native graph membership.».
  Модель: «Стриминговые chunks одного сообщения объединяются; альтернативные представления не
  дублируются.».
  Модель: «Tool-only записи не считаются user messages.».
  Модель: «Неподдержанный узел явно снижает полноту; он не становится пустым ответом.».
  Модель: «Reasoning/внутренние opaque payloads не нужны для обзора и не индексируются как чат.».
  Модель: «SearchChunk — целое логическое поле или сообщение.».

- [X] T042 [P] [US2] Реализовать bounded Codex history reader для paginated/JSONL представлений. Файл: `src/sessions_manager/sources/codex.py`.
  Зависимости: T041, T034.
  Whitelisted ThreadItem normalization, ordinals/item IDs, projection cursors и источник дат; один
  native event не дублировать по двум representations; paired DB inconsistency отражать stale/partial
  без app-server/repair.

- [X] T043 [P] [US2] Реализовать Claude graph и chunk normalization без удвоения сообщений. Файл: `src/sessions_manager/sources/claude.py`.
  Зависимости: T041, T035.
  Разобрать подтверждённые user/assistant/block forms, branch parent linkage, stream-vs-snapshot
  frames и tool actions. Длинный/неполный разговор не выдавать за пустой; subagents не продвигать в
  root произвольно.

- [X] T044 [P] [US2] Реализовать Grok ACP history reconstruction и fallback representations. Файл: `src/sessions_manager/sources/grok.py`.
  Зависимости: T041, T036.
  Собирать chunks по IDs в native порядке, учитывать incomplete tail/compaction и возвращать
  content-search доступность только при поддержанной структуре. Не считать chat_history вторым
  разговором.

- [X] T045 [P] [US2] Реализовать bounded Cursor wire projection и достижимый history graph. Файл: `src/sessions_manager/sources/cursor_wire.py`.
  Также: `src/sessions_manager/sources/cursor.py`.
  Зависимости: T041, T037.
  Лимиты source contract: blob <=32 МиБ, nesting <=64, varint <=10 bytes, <=100 000 nodes; types
  0/1/2/5, visited set, namespace predicates. Не импортировать vendor JS, pickle или keys; unknown
  codec снижает capability.

- [X] T046 [P] [US2] Реализовать точную Unicode-подстроку, filters/sorts и FTS5 candidate index. Файл: `src/sessions_manager/search.py`.
  Зависимости: T041, T038.
  str.casefold без удаления диакритики; external-content trigram + escaped literal MATCH и final
  instr; short-query scan точный, без LIKE wildcard semantics. Сочетание source/project/dates/scope и
  ties по ID.
  Модель: «Folded text = str.casefold(); native text и диапазоны отображения хранятся отдельно.».
  Модель: «Никаких пользовательских wildcard/FTS operators.».
  Модель: «Вывод — локальный timezone; неоднозначное время не проходит точный фильтр периода.».
  Модель: «Разбиение большого сообщения на физические страницы не должно терять совпадение через их
  границу; без такой проверки индекс не может называться полным.».

- [X] T047 [US2] Подключить content indexing и incremental invalidation к refresh/catalog. Файл: `src/sessions_manager/discovery.py`.
  Также: `src/sessions_manager/catalog.py`.
  Зависимости: T042, T043, T044, T045, T046, T040.
  Разделить enumeration/history/search completion; append vs replace/truncate, schema/Unicode upgrade
  invalidation, per-session atomic publish и cached-as-of. Не скрывать incomplete index ради latency;
  проверить early full benchmark.
  Enumeration scope и QuerySpec вывода разделены: никакой reconciliation по отфильтрованной
  странице; root completion означает полное чтение выбранного root.

- [X] T048 [US2] Реализовать детали, paged history, literal rendering и interactive search/filter/reset. Файл: `src/sessions_manager/ui/app.py`.
  Также: `src/sessions_manager/ui/screens.py`.
  Зависимости: T047, T039.
  Selection по стабильному ID, provenance timestamps/unknown fields, tool events не исполняются,
  ANSI/OSC/markup не управляют терминалом. Обновление не переключает пользователя на другую строку.

- [X] T049 [US2] Подключить show и полную выборку list к CLI-контракту. Файл: `src/sessions_manager/cli.py`.
  Зависимости: T048, T039.
  Metadata+content query, source/project/date AND, repeated source OR, scope visible/hidden/all,
  inclusive local dates, JSON show events/next_offset и errors/partial exit; green US2 сценарии и
  SC-002/003/007 evidence.

**Checkpoint**: Обзор + содержательный поиск + paged details работают; полный SC-002 проверяется без подмены partial результата complete.

---

## Phase 5: User Story 3 - Продолжить работу в исходном CLI (Priority: P1)

**Goal**: Передать точный conversation ID и cwd правильному native CLI в текущем терминале или Warp без нового разговора, prompt и bypass flags.

**Independent Test**: Synthetic child фиксирует exact argv/cwd четырёх источников; TUI возвращается после exit/Ctrl-C. Missing cwd/CLI и changed identity дают отказ/выбор; Warp ticket одноразовый, delivered не считается conversation_loaded.

**Traceability**: FR-009–FR-012, FR-025–FR-027; SC-004; US3 scenarios 1–4.

### Tests for User Story 3 (обязательный TDD / RED)

- [X] T050 [P] [US3] Написать и запустить падающие LaunchRequest validation/persistence tests. Файл: `tests/unit/test_launch_models.py`.
  Зависимости: T049.
  Exact identity/fingerprint/executable/cwd, current|warp, owner/context allowlist, 120s token expiry,
  single-use states, отсутствие copied env/transcript и запрет ложного conversation_loaded.
  history_locator независим от execution cwd; unverified binding возвращает ManualResumeGuide
  вместо LaunchRequest и не создаёт ticket.

- [X] T051 [P] [US3] Написать и запустить падающие контракты exact resume argv четырёх CLI. Файл: `tests/contract/test_resume_commands.py`.
  Зависимости: T049.
  contracts/launch.md: Codex resume ID -C CWD, Claude --resume ID, Cursor --workspace CWD --resume ID,
  Grok --cwd CWD --resume ID; executable абсолютный. No prompt/fork/latest/bypass, generic agent и
  view-only root; dry-run ничего не запускает.
  Для нового cwd проверить сохранение исходного history_locator/native ID через независимый
  fixture resolver; unsupported/unverified combo отказывает до child, не ищет другую историю
  в новом workspace и возвращает только проверенную manual instruction.

- [X] T052 [P] [US3] Написать и запустить падающие проверки foreground handoff и возврата TUI. Файл: `tests/acceptance/test_resume.py`.
  Зависимости: T049.
  Harmless child и synthetic records: inherited stdio без transcript capture, missing/moved cwd
  выбор/отмена, changed session/CLI failure, suspend/refresh, nonzero exit/Ctrl-C и normal terminal
  restoration; US3 scenarios 1/3/4.
  При отказе одновременно доступны причина, другая папка/отмена и manual guide; в non-TTY
  нет ожидания input. Одного совпадения argv недостаточно для доказательства прежнего контекста.

- [X] T053 [P] [US3] Написать и запустить падающие Warp config/ticket transport tests. Файл: `tests/unit/test_warp.py`.
  Также: `tests/integration/test_launch_ticket.py`, `tests/acceptance/test_warp.py`.
  Зависимости: T049.
  Fixed private TOML, one-shot claim, TTL/replay/tamper/owner validation, fake open delivery/timeout,
  manager paths quoting и braces reject; native ID/cwd/title/secret не в shell/URI. Generated
  artifacts живут до claim/expiry.

- [X] T054 [P] [US3] Создать opt-in падающий runtime сценарий Warp с harmless fixture child. Файл: `tests/acceptance/test_warp_runtime.py`.
  Зависимости: T049.
  --run-warp, без реального provider: exact argv/cwd/ack с spaces/кириллицей/quotes/$/braces,
  доставленный URI не доказывает resume. Обычный test run не открывает Warp; US3 scenario 2.

### Implementation for User Story 3 (после соответствующего RED)

- [X] T055 [US3] Добавить LaunchRequest модель, private manifest и one-shot state persistence. Файл: `src/sessions_manager/models.py`.
  Также: `src/sessions_manager/catalog.py`.
  Зависимости: T050.
  Все поля data-model.md §6, включая history_locator отдельно от execution cwd и результат
  ManualResumeGuide; owner/fingerprint/context validation; helper и UI различают
  delivery/claim/process/loaded. Не расширять stored environment.
  Модель: «target (current / warp)».
  Модель: «В manifest нет скопированного окружения, credential values или transcript.».
  Модель: «Ticket случайный, одноразовый, срок 120 секунд.».
  Модель: «requested -> claimed -> handoff_attempted -> child_exited / exec_failed;».
  Модель: «requested -> expired / delivery_failed.».
  Модель: «URI delivered не равно claimed, а handoff_attempted не равно conversation_loaded.».
  Модель: «Удаляются только manager-owned launch artifacts после завершения/expiry, не session
  trash.».
  Модель: «Выбор нового cwd для resume меняет LaunchRequest, а не молча переписывает native историю.».
  Модель: «Смена cwd не меняет history_locator или session_uid.».

- [X] T056 [US3] Реализовать native resume-plan builders и доказанный source-root context. Файл: `src/sessions_manager/sources/base.py`.
  Также: `src/sessions_manager/sources/codex.py`, `src/sessions_manager/sources/claude.py`,
  `src/sessions_manager/sources/cursor.py`, `src/sessions_manager/sources/grok.py`.
  Зависимости: T055, T051.
  Передавать exact ID/cwd/абсолютный CLI по contracts/launch.md; custom roots view-only до
  доказательства native binding, только CODEX_HOME/CLAUDE_CONFIG_DIR allowlisted overrides. Никакого
  автоматического latest/new/fork или ambiguous agent.
  Подтвердить native binding исходной истории для выбранного execution cwd. Приведённые argv
  не означают разрешение слепо заменить workspace: unknown/unsupported binding возвращает
  manual guide без переноса native data, замены ID, child или Warp ticket.

- [X] T057 [US3] Реализовать повторную валидацию и foreground subprocess service. Файл: `src/sessions_manager/launch.py`.
  Зависимости: T056, T052.
  shell=False, inherited terminal I/O, source generation/cwd/executable recheck; не захватывать native
  transcript в logs. Результат child exit/exec error не объявляет conversation_loaded; отмена не
  создаёт новую сессию.
  Повторно проверить history_locator и его привязку к новому cwd; запускать только verified
  план. Fallback guide содержит лишь известные шаги/команду справки с безопасным quoting.

- [X] T058 [US3] Реализовать документированный Warp Tab Config и private one-shot helper. Файл: `src/sessions_manager/warp.py`.
  Зависимости: T057, T053, T054.
  tomli-w, terminal pane shell=zsh/directory=/, fixed manager launcher+data-dir+opaque ticket, no
  source metadata в config. /usr/bin/open argv, owner-only manifests, атомарный claim, expiry/replay,
  direct child; удалять только собственные launch artifacts. Runtime gate отдельно, не native user
  session.

- [X] T059 [US3] Подключить resume/dry-run/cwd/terminal и внутренний _launch к CLI. Файл: `src/sessions_manager/cli.py`.
  Зависимости: T058, T051, T053.
  Global data-dir тот же у helper; hidden _launch валидирует owner/token и не принимает arbitrary
  commands. Отсутствующий cwd non-TTY требует --cwd; Warp delivery/pending/expiry и exit=8
  различаются.
  При неподтверждённой/неподдержанной привязке вернуть exit 4 с причиной, вариантами
  другой папки/отмены и data.manual_resume_guide; инструкции не писать в diagnostics и не выполнять.

- [X] T060 [US3] Подключить выбор сессии/терминала и безопасный suspend-return цикл. Файл: `src/sessions_manager/ui/app.py`.
  Также: `src/sessions_manager/ui/screens.py`.
  Зависимости: T059, T052.
  Выбор current/Warp и нового cwd явный; остановить scan workers/короткие source readers перед
  foreground handoff, App.suspend, восстановить UI при exit/interrupt и refresh того же ID; green US3
  без реальных AI-сессий.
  Экран отказа одновременно показывает причину, выбор другой папки/отмену и manual guide;
  ручная инструкция не заменяет другие варианты и не запускается автоматически.

**Checkpoint**: P1 scope готов при passing automated gates; opt-in harmless Warp runtime и реальные native checks имеют отдельную честно записанную степень проверки.

---

## Phase 6: User Story 4 - Убрать лишнее и сохранить возможность восстановления (Priority: P2)

**Goal**: Скрыть сессию без изменения source либо выполнить exact подтверждённую local trash/restore/purge операцию с recoverable данными.

**Independent Test**: Только synthetic bundles: hide/restart/unhide; cancel/expired/stale plan ничего не меняют; trash и restore сохраняют selected history и neighbors; no-overwrite conflict, interrupted retry и batch дают per-target результаты. Codex paginated cleanup недоступна без fake success.

**Traceability**: FR-013–FR-019, FR-025–FR-027; SC-006; US4 scenarios 1–7.

### Tests for User Story 4 (обязательный TDD / RED)

- [X] T061 [P] [US4] Написать и запустить падающие OperationPlan/TrashEntry/journal validation tests. Файл: `tests/unit/test_cleanup_models.py`.
  Также: `tests/integration/test_operation_catalog.py`.
  Зависимости: T060.
  Точный target/action/fingerprint binding, 5-minute expiry, atomic consumption, operation
  idempotency, per-artifact stages и запрет произвольного payload path; все field/state constraints
  data-model §5.

- [X] T062 [P] [US4] Написать и запустить падающие проверки hide/unhide persistence и scope. Файл: `tests/integration/test_hide.py`.
  Зависимости: T060.
  Single/batch hide, restart/refresh, aliases/tombstones, hidden resume, visible/hidden/all counters;
  никакие native history bytes или project files не меняются.

- [X] T063 [P] [US4] Написать и запустить падающие проверки durable backup и Darwin no-replace filesystem primitives. Файл: `tests/integration/test_fsops.py`.
  Зависимости: T060.
  Hashes/fsync, symlink/hardlink ambiguity, containment/UID, low disk/access denied,
  same-device/unsupported volume, atomic restore collision/race. stat+replace не считается
  no-overwrite; все inputs synthetic.

- [X] T064 [P] [US4] Написать и запустить падающие Claude exact-bundle/neighbor cleanup contracts. Файл: `tests/contract/test_claude_cleanup.py`.
  Зависимости: T060.
  Только selected transcript и доказанные companions/subagents; shared
  project/history.jsonl/stats-cache и project files неизменны; неизвестные зависимости и active
  runtime блокируют mutation.

- [X] T065 [P] [US4] Написать и запустить падающие Grok local-only bundle cleanup contracts. Файл: `tests/contract/test_grok_cleanup.py`.
  Зависимости: T060.
  Complete summary/logs/snapshots + доказанная shared-cache topology; active_sessions/PID reuse,
  changed bundle. Любой remote/native sessions delete, teardown или signal kill запрещён.

- [X] T066 [P] [US4] Написать и запустить падающие Cursor per-chat/WAL cleanup contracts. Файл: `tests/contract/test_cursor_cleanup.py`.
  Зависимости: T060.
  Полный coherent store/WAL/meta/companions, соседние chats и global persistent-owner state не
  изменяются. Нет CLI pager recursive delete; active/uncoordinated writers и unknown profile блокируют
  mutation.

- [X] T067 [P] [US4] Написать и запустить падающие общие safety/confirmation cleanup contracts. Файл: `tests/contract/test_cleanup_protocol.py`.
  Зависимости: T060.
  Codex paginated unavailable; known-active block без force, unknown требует closed assertion; exact
  preview token, changed/expired/cancelled plan и unsupported device не меняют source. Runtime safety
  profile не включается по одному reader.

- [X] T068 [P] [US4] Написать и запустить падающие crash/retry/batch/restore/purge integration tests. Файл: `tests/integration/test_cleanup_recovery.py`.
  Зависимости: T060.
  Fault на каждой copy/hash/fsync/rename/journal границе; manifest-vs-files recovery, повтор того же
  op, mixed batch, restore target race/upgrade conflict, no whole-DB rollback и purge traversal;
  сохранность backup/neighbor hashes.

- [X] T069 [P] [US4] Написать и запустить падающие уборочные CLI/TUI acceptance tests. Файл: `tests/contract/test_cleanup_commands.py`.
  Также: `tests/acceptance/test_cleanup.py`.
  Зависимости: T060.
  US4 scenarios 1–7: hide/unhide, preview без mutation, --confirm и --assert-closed, default cancel
  modal, trash list/restore/purge, exact JSON item results/exit codes и отдельное irreversible
  confirmation.

### Implementation for User Story 4 (после соответствующего RED)

- [X] T070 [US4] Добавить OperationPlan/TrashEntry/OperationItem и durable manager schema. Файл: `src/sessions_manager/models.py`.
  Также: `src/sessions_manager/catalog.py`, `src/sessions_manager/sources/base.py`.
  Зависимости: T061.
  Все поля §5, versioned artifact manifests/owner/profile/hash/modes, atomic token-to-operation
  binding и per-target receipts. Define exact cleanup bundle protocol; Codex не создаёт ложный trash
  entry.
  Модель: «action (trash / restore / purge)».
  Модель: «Token действует 5 минут, не является generic --yes, связан со всем показанным набором и
  действием.».
  Модель: «Изменение набора/источника/профиля требует нового preview.».
  Модель: «Путь payload всегда вычисляется из ID внутри manager trash, не принимается из
  пользовательского произвольного пути.».
  Модель: «live/hidden -> preview -> backup_ready -> removing -> trashed;».
  Модель: «trashed -> restore_preview -> restoring -> restored;».
  Модель: «trashed -> purge_preview -> purging -> purged;».
  Модель: «после source change любая ошибка -> recovery_required/conflict, не generic success;».
  Модель: «до source change ошибка -> failed_no_change/cancelled.».

- [X] T071 [US4] Реализовать owner/containment проверки, verified backups и no-replace moves. Файл: `src/sessions_manager/fsops.py`.
  Зависимости: T070, T063.
  Закрытые complete bundles, pre/post fingerprints, SHA-256 и fsync files/dirs; Darwin
  renameatx_np(RENAME_EXCL), unsupported/cross-device отказ без copy+unlink fallback. Recovery
  сохраняет различающиеся версии; native общие базы не заменяются.

- [X] T072 [P] [US4] Реализовать persistent single/batch hide/unhide без source writes. Файл: `src/sessions_manager/catalog.py`.
  Зависимости: T070, T062.
  Stable IDs и shared selection scopes; hidden flag переживает refresh/перезапуск и не мешает resume.
  Корзина и hide — разные состояния, hidden counts корректны.

- [X] T073 [P] [US4] Реализовать доказанный Claude cleanup manifest и quiescence guards. Файл: `src/sessions_manager/sources/claude.py`.
  Зависимости: T071, T064.
  Whitelist только session-owned transcript+companions; не менять shared project/history/stats или
  workspace. Unknown companions/writers/version отключают capability; никакого native project purge.

- [X] T074 [P] [US4] Реализовать Grok локальный cleanup manifest без cloud/native delete. Файл: `src/sessions_manager/sources/grok.py`.
  Зависимости: T071, T065.
  Полный session subtree, PID/start/executable evidence и shared-index dependency proof. Если safe
  invalidation topology не доказана, unavailable, а не hide под видом удаления. Никогда sessions
  delete/remote/teardown.

- [X] T075 [P] [US4] Реализовать Cursor coherent per-chat cleanup manifest. Файл: `src/sessions_manager/sources/cursor.py`.
  Зависимости: T071, T066.
  Включить нужные store/WAL/meta/companions, не затрагивая neighbors и global owner.
  Writer/quiescence/codec/schema checks; отсутствие lock не трактовать как inactive; неполная topology
  запрещает mutation.

- [X] T076 [US4] Реализовать exact cleanup preview, confirmation и source revalidation. Файл: `src/sessions_manager/cleanup.py`.
  Зависимости: T072, T073, T074, T075, T067.
  Состав/bytes/unknown/effect/expiry, manager operation lock, stable action/fingerprint binding,
  consumed token idempotency. Known active запрещён, unknown требует утверждения о закрытости;
  наблюдаемый writer нельзя обойти assertion.

- [X] T077 [US4] Реализовать verified backup -> journal -> exact source relocation -> trashed. Файл: `src/sessions_manager/cleanup.py`.
  Зависимости: T076, T068.
  До BACKUP_READY source не меняется; после каждой стадии durable progress. Same-device exact owned
  artifacts, complete payload+neighbor verification перед success; сохраняя backup при
  подозрении/частичном отказе. Search membership исключается только по подтверждённому состоянию.

- [X] T078 [US4] Реализовать согласование manifest/files и идемпотентный crash/batch recovery. Файл: `src/sessions_manager/cleanup.py`.
  Также: `src/sessions_manager/catalog.py`.
  Зависимости: T077, T068.
  Crash между rename и journal не угадывается. Reconcile expected locations/hashes, preserve both
  versions on conflict, per-target outcomes и retry того же operation; не переоценивать dynamic
  selection.
  Модель: «Между каталогом и filesystem нет фиктивной общей транзакции.».
  Модель: «Повтор по op_id возвращает/завершает тот же результат, не выбирает объект заново.».
  Модель: «Batch содержит отдельные OperationItem.».

- [X] T079 [US4] Реализовать подтверждённое no-overwrite восстановление полного bundle. Файл: `src/sessions_manager/cleanup.py`.
  Зависимости: T078.
  Проверить source profile/owner/root/original targets и hashes; atomic no-replace, не
  exists()+replace. Existing/missing root/новая schema дают понятный conflict; retain trash до
  verified restore, не менять project files/общую DB.

- [X] T080 [US4] Реализовать отдельный irreversible purge только manager trash IDs. Файл: `src/sessions_manager/cleanup.py`.
  Зависимости: T079.
  Новый exact preview/token; no arbitrary source path/glob/all/auto-age. Traverse только собственный
  entry, interrupted purge resumable, minimal receipt без transcript. Не обещать secure erase или
  удаление cloud/native memory.

- [X] T081 [US4] Подключить hide/unhide/delete/trash list/restore/purge к CLI. Файл: `src/sessions_manager/cli.py`.
  Зависимости: T080, T069.
  Первый delete/restore/purge — только operation_plan; --confirm связывается с exact набором, unknown
  нуждается в --assert-closed. Item states/trash_id/recovery_options и exit=3 при partial; Codex
  unsafe выдаёт reason без mutation.

- [X] T082 [US4] Подключить обратимое скрытие и безопасные cleanup dialogs/results в TUI. Файл: `src/sessions_manager/ui/app.py`.
  Также: `src/sessions_manager/ui/screens.py`.
  Зависимости: T081, T069.
  Batch selection по IDs, preview exact scope, default focus cancel, separate purge warning,
  hidden/trash views и restore conflicts; recovery_required виден после restart. Green US4 scenarios,
  не запускать проверки на реальных историях.

**Checkpoint**: Включаются только профили с доказанным позитивным cleanup/recovery gate. Для unsupported/unsafe операции видна причина; эта ветка не считается прошедшим положительным mutation test.

---

## Phase 7: User Story 5 - Понять объём и использование сессий (Priority: P2)

**Goal**: Показать per-session и групповые lifetime metrics с корректными unique facts, coverage, missing values и размерами.

**Independent Test**: Golden corpus со shared API IDs и snapshots: суммы точно соответствуют ожидаемому union, null отличается от 0, cached/reasoning не добавляются повторно. Cursor lifetime unknown и shared_usage видны; период отбирает сессии, не обещает расход только за даты.

**Traceability**: FR-020–FR-024, FR-027; SC-005, SC-007; US5 scenarios 1–5.

### Tests for User Story 5 (обязательный TDD / RED)

- [X] T083 [P] [US5] Написать и запустить падающие UsageFact/membership/snapshot/catalog tests. Файл: `tests/unit/test_usage_models.py`.
  Также: `tests/integration/test_usage_catalog.py`.
  Зависимости: T082.
  Nonnegative integer-or-null без bool, unique proven request identity, many-to-many membership,
  scope/epoch/revision, overlapping/non_summable snapshots, atomic replacement и coverage/context
  kinds.

- [X] T084 [P] [US5] Написать и запустить падающие Codex usage normalization contracts. Файл: `tests/contract/test_codex_usage.py`.
  Также: `tests/support/codex_factory.py`.
  Зависимости: T082.
  response_id usage vs turn/thread snapshots, payload.thread_id != container, receipt
  duplicates/revisions, legacy token_count epochs, missing receipts/partial projection и
  cache/reasoning subsets; не суммировать альтернативные representations.

- [X] T085 [P] [US5] Написать и запустить падающие Claude message.id/cache accounting contracts. Файл: `tests/contract/test_claude_usage.py`.
  Также: `tests/support/claude_factory.py`.
  Зависимости: T082.
  Последний корректный monotonic usage, conflicting/regressing rows, copied/forked API IDs,
  uncached+read+creation input и TTL subtotals; одинаковый текст разных API calls не dedup,
  stats-cache не смешивается.

- [X] T086 [P] [US5] Написать и запустить падающие Grok snapshot/coverage contracts. Файл: `tests/contract/test_grok_usage.py`.
  Также: `tests/support/grok_factory.py`.
  Зависимости: T082.
  usage.json session единожды, turns/modelUsage overlap, usageIsIncomplete/costIsPartial, absent keys
  vs known 0, snapshots без доказанной независимости и context occupancy не lifetime; source network
  запрещён.

- [X] T087 [P] [US5] Написать и запустить падающие Cursor unknown-lifetime/context-only contracts. Файл: `tests/contract/test_cursor_usage.py`.
  Также: `tests/support/cursor_factory.py`.
  Зависимости: T082.
  usedTokens/maxTokens — отдельный context metric; input/output/total lifetime null с
  причиной/coverage. Не делать billing query, tokenization estimate или default zero; messages
  считаются из достижимого нормализованного графа.

- [X] T088 [P] [US5] Написать и запустить падающие aggregate union/coverage/grouping tests. Файл: `tests/unit/test_statistics.py`.
  Зависимости: T082.
  Выборка lifetime sessions по last activity, shared fact union, snapshots disjoint/overlap,
  shared_usage bucket, nullable categories/zero, user+assistant vs tools, hidden включены/корзина
  исключена по default; известные expected totals.

- [X] T089 [P] [US5] Написать и запустить падающие stats CLI/TUI acceptance tests. Файл: `tests/contract/test_stats_commands.py`.
  Также: `tests/acceptance/test_statistics.py`.
  Зависимости: T082.
  US5 scenarios 1–5: --session, filters/scope, source/project/day groups, partial coverage/as_of,
  known bytes vs shared store size, lifetime-period label и неизвестный Cursor usage; JSON
  scope/metrics/groups/accounting_mode.

### Implementation for User Story 5 (после соответствующего RED)

- [X] T090 [US5] Добавить UsageFact/UsageMembership/UsageSnapshot и manager ledger migrations. Файл: `src/sessions_manager/models.py`.
  Также: `src/sessions_manager/catalog.py`, `src/sessions_manager/sources/base.py`.
  Зависимости: T083.
  Все поля data-model.md §4, exact request identity/provenance, nullable categories, owner attribution
  и per-session membership. Snapshot-only scope не превращать в invented request facts.
  Модель: «owner_native_session_id (если доказан)».
  Модель: «total integers-or-null, completeness, source evidence revision.».
  Модель: «summability (disjoint / overlapping / unknown)».
  Модель: «Авторитетный snapshot заменяется новым, не складывается с собой или receipts того же
  scope.».
  Модель: «Локальный context occupancy хранится отдельной метрикой с kind=context, не lifetime
  usage.».
  Модель: «Один API response/message — один факт, даже если находится в нескольких histories.».
  Модель: «Разные request IDs с одинаковым текстом остаются разными фактами.».
  Модель: «Конфликтные receipts не объединяются арифметически: сохраняется incomplete evidence.».
  Модель: «Native identity может быть глобальной или namespace-scoped только по проверенному контракту
  источника.».

- [X] T091 [P] [US5] Реализовать Codex per-response facts и authoritative snapshot fallback. Файл: `src/sessions_manager/sources/codex.py`.
  Зависимости: T090, T084.
  Ownership по payload.thread_id, dedup по проверенному response identity, usage отдельно от
  turn/thread totals. Legacy/compaction incompleteness и отсутствующий original не дают выдуманных
  фактов; cache/reasoning не добавляются повторно.

- [X] T092 [P] [US5] Реализовать Claude last-valid API usage и cache category normalization. Файл: `src/sessions_manager/sources/claude.py`.
  Зависимости: T090, T085.
  message.id fact, fork memberships и native context identity; normalized
  input=uncached+cache_read+cache_creation, total=input+output. Conflicting/nonmonotonic evidence
  partial, nested cache TTL не прибавляется.

- [X] T093 [P] [US5] Реализовать Grok session snapshot и явную incomplete/summability semantics. Файл: `src/sessions_manager/sources/grok.py`.
  Зависимости: T090, T086.
  Единственный session lifetime snapshot, per-turn/model views не суммируются; missing usage/key
  unknown. Preserve incomplete flags и fork/provenance accounting; не использовать signals как ledger
  и не вычислять деньги.

- [X] T094 [P] [US5] Реализовать честные Cursor lifetime-unknown и context-only metrics. Файл: `src/sessions_manager/sources/cursor.py`.
  Зависимости: T090, T087.
  Не объявлять usage реализованной заглушкой с 0: вернуть unavailable/not_recorded для lifetime,
  отдельный kind=context только при подтверждённых данных, messages из нормализованного reachable
  graph.

- [X] T095 [P] [US5] Реализовать безопасную агрегацию выбранных lifetime histories. Файл: `src/sessions_manager/statistics.py`.
  Зависимости: T090, T088.
  Использовать общий QuerySpec/filters US2, safe unique-fact union и per-category coverage; не
  складывать перекрывающиеся group totals.
  Модель: «Per-session total описывает полную историю выбранной сессии.».
  Модель: «Сводка объединяет уникальные подтверждённые факты; это не сумма session totals.».
  Модель: «Snapshot-only scopes суммируются только при доказанной независимости; иначе исключаются из
  безопасной суммы с явным incomplete/non_summable покрытием.».
  Модель: «Известные 0 сохраняются. Нет поля — null, если профиль не доказывает семантику default
  zero.».
  Модель: «Total не включает cache/reasoning повторно.».
  Модель: «Для каждой категории показываются selected_sessions, known_sessions, incomplete_sessions,
  known_fact_count и included/excluded snapshot scopes.».
  Модель: «В группировке факт, принадлежащий нескольким различным группам выбранных сессий, попадает в
  явную группу shared_usage.».
  Модель: «Фильтр периода отбирает сессии по последней активности; это не расход событий за период.».
  Модель: «Message count учитывает нормализованные user/assistant events с доказанными identities,
  отдельно от tool events; неполные/неоднозначные данные сохраняют признак partial.».

- [X] T096 [US5] Подключить incremental usage ingestion и ledger reconciliation к refresh. Файл: `src/sessions_manager/discovery.py`.
  Также: `src/sessions_manager/catalog.py`.
  Зависимости: T091, T092, T093, T094, T095.
  Новый scan заменяет snapshots, dedup receipts/memberships, сохраняет shared facts соседних сессий
  при hide/trash и не считает cache update новым расходом. Per-category completeness/as_of и stable
  query scope публикуются атомарно.

- [X] T097 [US5] Реализовать session/aggregate statistics view с объяснением неполноты. Файл: `src/sessions_manager/ui/app.py`.
  Также: `src/sessions_manager/ui/screens.py`.
  Зависимости: T096, T089.
  Source/project/day, lifetime-period label, known vs unknown 0, coverage/shared_usage, hidden scope и
  корзина, известный session bytes vs общий store; не называть elapsed span активными часами.

- [X] T098 [US5] Подключить stats, --session/group-by и JSON coverage к общему CLI. Файл: `src/sessions_manager/cli.py`.
  Зависимости: T097, T089.
  Default scope=all включая hidden/без trash, explicit query/filter parity,
  scope=selected_session_lifetimes. Green US5 golden totals, honest incomplete/non-summable output и
  exit semantics.

**Checkpoint**: Пять пользовательских сценариев реализованы в пределах явно проверенных source capabilities; можно выполнять финальную сквозную приёмку.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Подтвердить производительность, упаковку, документацию и интегральные gates. Не добавлять новые features вне спецификации.

- [X] T099 Выполнить полные SC-002 benchmarks после всех source/usage/cleanup интеграций и записать evidence. Файл: `tests/performance/test_overview_budget.py`.
  Также: `tests/performance/test_discovery_budget.py`, `tests/support/make_corpus.py`,
  `specs/001-session-command-center/validation.md`.
  Зависимости: T098.
  10 000 synthetic sessions / 1 ГиБ на целевой машине, cold <=10 с и warm overview/search/navigation
  <=2 с, все queries complete. Записать hardware/OS/seed/cache/as_of; при превышении оптимизировать
  измеренный bottleneck под падающим regression/performance тестом, не ослаблять target.

- [X] T100 Согласовать пользовательскую документацию с фактическими командами, матрицей профилей и recovery ограничениями. Файл: `README.md`.
  Также: `specs/001-session-command-center/quickstart.md`,
  `specs/001-session-command-center/contracts/cli.md`,
  `specs/001-session-command-center/contracts/sources.md`,
  `specs/001-session-command-center/contracts/launch.md`,
  `specs/001-session-command-center/contracts/cleanup.md`.
  Зависимости: T099.
  Установка/запуск, no-arg UX, конфигурация roots, offline/privacy и trash recovery; честные Codex
  cleanup/Cursor tokens/Warp status. Quickstart становится реально исполнимым, исключить устаревшие
  будущие команды и не добавлять незапрошенные features.

- [X] T101 Проверить wheel/sdist, console entry и locked install в отдельном временном окружении. Файл: `pyproject.toml`.
  Также: `uv.lock`, `tests/contract/test_cli_common.py`,
  `specs/001-session-command-center/validation.md`.
  Зависимости: T100.
  uv build и isolated install для поддержанной Python >=3.12 среды; sessions --help/--version и
  synthetic smoke через явный fixture config. Не устанавливать тестовый build глобально и не подменять
  HOME; исправления поведения проходят TDD.

- [X] T102 Прогнать relevant Ruff/pytest/quickstart gates и оформить итоговую traceability для ревью. Файл: `specs/001-session-command-center/validation.md`.
  Также: `specs/001-session-command-center/quickstart.md`, `tests/acceptance/test_overview.py`,
  `tests/acceptance/test_history.py`, `tests/acceptance/test_resume.py`,
  `tests/acceptance/test_cleanup.py`, `tests/acceptance/test_statistics.py`.
  Зависимости: T101.
  Собрать red/green evidence FR-001–FR-027/SC-001–SC-008, privacy/read-only/neighbor checks и opt-in
  harmless Warp runtime. Реальные native conversations не запускать автоматически; непроведённые
  ручные gates не считать passing. git diff без private histories/catalog/corpora/credentials;
  evidence готово для GitHub PR.

**Checkpoint**: Evidence для всех выполненных gates готово к ревью; непроведённые проверки и unsupported capabilities не выдаются за passing.

---

## Dependencies & Execution Order

### Phase Dependencies

| Фаза | Задачи | Обязательный вход |
| ---- | ------ | ----------------- |
| 1 | T001–T003 (3) | Нет |
| 2 | T004–T015 (12) | Setup |
| 3 | T016–T032 (17) | Полные foundations |
| 4 | T033–T049 (17) | Checkpoint предыдущей фазы |
| 5 | T050–T060 (11) | Checkpoint предыдущей фазы |
| 6 | T061–T082 (22) | Checkpoint предыдущей фазы |
| 7 | T083–T098 (16) | Checkpoint предыдущей фазы |
| 8 | T099–T102 (4) | Checkpoint предыдущей фазы |

```mermaid
flowchart LR
    Setup --> Foundations --> US1
    US1 --> US2
    US2 -->|shared files barrier| US3
    US3 -->|shared files barrier| US4
    US4 -->|shared files barrier| US5
    US5 --> Polish
```

Это исполнимый порядок редактирования, а не требование, чтобы статистика зависела от
удаления. Функционально US3/US4 используют metadata core US1, US5 — history core US2;
каждый сценарий проверяется отдельно на synthetic state без выполнения остальных действий.
US2→US3→US4→US5 сериализованы из-за общих models/catalog/cli/ui и provider files.
Перестановка этих этапов требует отдельного согласования файловых изменений; текущий
список уже даёт безопасный линейный порядок и параллельность внутри фаз.

### Within Each User Story

- Сначала relevant contract/unit/integration/acceptance tests и подтверждённый RED.
- Затем constrained models/schema → adapters/services → CLI/TUI → integration checkpoint.
- Включённая source capability требует positive и negative fixture gates. Unknown/unsafe
  корректно отключается, но не засчитывается как реализованный положительный сценарий.
- Native mutations никогда не проверяются на личных историях. Для Codex paginated профиль
  целенаправленно возвращает unavailable; это решение дизайна, не задача обойти safety.
- Поведение уже законченных историй не ломается последующими migrations/интеграциями.
- Red/green evidence собирается для финального validation.md без конкурентной записи
  нескольких [P] задач в общий файл.

### Parallel Opportunities

Параллельны только строки, явно помеченные [P], после выполнения их dependencies.
Тестовые файлы и provider factories разных источников независимы; одноимённые provider
файлы разных фаз никогда не редактируются одновременно. Общие catalog/models/UI шаги
сериализованы. Параллельных задач: **68**, готовых волн: **12**.

## Parallel Example: User Story 1

После foundations: T016, T017, T018, T019, T020, T021, T022, T023
пишут разные tests/support files.
После RED: T024, T025, T026, T027, T028, T029
не пересекают production/test utility paths. Discovery/UI/CLI ожидают эту готовую основу.

## Parallel Example: User Story 2

После US1: T033, T034, T035, T036, T037, T038, T039, T040 — разные тестовые файлы.
После T041: T042, T043, T044, T045, T046
могут выполняться вместе. T047 объединяет их после завершения, UI/CLI идут последовательно.

## Parallel Example: User Story 3

После US2: T050, T051, T052, T053, T054 — независимые тесты.
Production steps T055–T060 идут последовательно: общие модели,
builders, service, transport и CLI/helper требуют законченных контрактов друг друга.

## Parallel Example: User Story 4

После US3: T061, T062, T063, T064, T065, T066, T067, T068, T069 — независимые файлы тестов.
После T070 и T071: T072, T073, T074, T075
пишут разные файлы. T076–T082 используют общий coordinator и сериализованы.

## Parallel Example: User Story 5

После US4: T083, T084, T085, T086, T087, T088, T089 — тестовая волна.
После T090: T091, T092, T093, T094, T095
независимы. Ingestion/UI/CLI после них не запускаются параллельно с изменением общих файлов.

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Выполнить Setup и все foundations: T001–T015.
2. Выполнить US1: T016–T032.
3. Проверить четыре источника, no-arg overview, healthy/partial/empty cases и stable IDs.
4. Демонстрировать только metadata overview и refresh, без обещания ещё не построенных действий.

MVP — **32 задачи**. Полный P1 scope с историей/поиском и resume/Warp — **60 задач**
(T001–T060). Это промежуточные полезные инкременты, не отметка всей feature complete.

### Incremental Delivery

US1 overview → US2 history/search → US3 resume → US4 reversible cleanup → US5 safe statistics.
После каждого checkpoint прогнать relevant regression checks; повторять/расширять их
только при новых изменениях или обнаруженном риске. Финальные performance/package/
documentation gates T099–T102 обязательны для всей feature.

### Parallel Team Strategy

Использовать перечисленные готовые волны как границы файловой независимости.
Менеджер задач может выполнять их последовательно; параллельность — возможность,
а не разрешение обходить RED, source safety или shared-file barriers.
Один владелец объединяет изменения models/catalog/cli/UI после готовности адаптеров.

## Notes

- Реализация и evidence отмечены checkbox задач. Ручные native/Warp/usability gates
  перечислены отдельно в validation.md и не объявляются passing.
- Story counts: US1=17,
  US2=17,
  US3=11,
  US4=22,
  US5=16; setup/foundations/polish=19.
- FR-027/TDD распространяется на все behavioral tasks, включая helpers, которые влияют
  на launch/cleanup. Disposable fixture generation — test infrastructure, не личные данные.
- Источники и матрица решений зафиксированы в research.md; при version drift не угадывать
  новый формат и не расширять destructive capability без contract tests.
- Не ослаблять SC-002 и не превращать context occupancy/unknown токены в lifetime расход.
- Не прекращать native процессы и не вызывать Grok remote deletion или Claude project purge.
- Нативный реальный resume не запускается автоматически ради отметки теста. Ручные gates
  и опциональный harmless Warp runtime фиксируются раздельно; отсутствие проверки — не passing.
- Изменения versioned source contracts/documentation публикуются через GitHub branch/PR
  с целью, validation и ограничениями; secrets, личные истории и private corpora не коммитятся.

## Follow-up: native-data regressions (2026-11-03)

- [X] T103 Reproduce Codex null usage, per-capability scan failure, default Claude cleanup and shortcut conflicts with synthetic regression tests in `tests/contract/`, `tests/integration/`, `tests/acceptance/`.
- [X] T104 Keep Codex metadata visible when optional usage/history is absent or invalid; preserve cached history on capability read failure in `src/sessions_manager/sources/codex.py` and `src/sessions_manager/discovery.py`.
- [X] T105 Resolve Claude cleanup runtime version without configuration edits, validate compatible mixed 2.1 JSONL shapes/closed workflow bundles, and keep fresh version/topology/activity checks for trash and restore in `src/sessions_manager/sources/base.py` and `src/sessions_manager/cleanup.py`.
- [X] T106 Replace case-sensitive refresh/resume shortcuts with F5 refresh, o open/resume and r restore within trash in `src/sessions_manager/ui/app.py` and `src/sessions_manager/ui/screens.py`; cover actual keyboard actions.
- [X] T107 Investigate Grok missing token metrics and project/history locations; preserve explicit not-recorded values when no native ledger exists. Update regression fixtures if a supported format was missed.
- [X] T108 Run relevant/full checks and read-only native verification; update README/contracts/validation and submit fixes through GitHub. Do not test deletion on personal sessions.

## Native compatibility and remaining capabilities (2026-11-03)

- [X] T109 Reproduce missing Cursor metadata sidecars and binary graph references with synthetic fixtures; recover metadata from verified sibling workspace context without guessing paths.
- [X] T110 Normalize supported Cursor graph variants and keep unknown nodes explicit; preserve metadata when optional graph data is incomplete.
- [X] T111 Detect supported Grok/Cursor runtime versions automatically for cleanup, retaining source topology/activity/closed-session validation and safe restore across process restarts.
- [X] T112 Verify native resume argument binding with installed CLI metadata and isolated disposable native stores; improve Codex missing-rollout/relocated-path capability reasons where proof permits.
- [ ] T113 Run the authorized harmless Warp runtime gate; repair transport if necessary without opening personal AI conversations. **Attempted, FAIL:** installed Warp accepted URI but never claimed the ticket; Computer Use denied access to Warp. Cause in native startup remains unverified. Current terminal guidance is implemented; gate remains open.
- [X] T114 Investigate Codex native cleanup/archival APIs and implement only a bounded reversible profile with verified recovery and neighbor protection; record any native limitation explicitly.
- [X] T115 Replace raw technical failure codes in human CLI/TUI with actionable explanations while preserving stable JSON codes.
- [X] T116 Update spec/contracts/research and validation, run relevant/full/package/performance gates, and publish reviewed changes through GitHub.

Remaining native capabilities (not silently marked implemented):
- [X] T117 Design/verify scoped local Grok shared-index cleanup and restore; current native local directories plus session_search.sqlite/grok.db are intentionally unavailable for trash. Remote delete and direct shared DB mutation remain excluded. Feasibility assessment completed by T139: the current native primitives cannot provide bounded reversible shared-index cleanup; capability stays unavailable.
- [ ] T118 Enable Codex cleanup only after a native API can bind exact confirmed descendant closure/revision and recovery. Current threadId-only cascade API does not satisfy this gate.

## Filtering and sorting — 2026-11-04

- [X] T119 Write and observe failing QuerySpec tests for combined model/activity/source/project/date filters, expanded sort fields, direction, unknown-last/stable ties and invalid values; reproduce missing Claude model metadata.
- [X] T120 Extend QuerySpec filtering/sorting with a fixed allowlist and compatible recent/oldest aliases; fill Claude model from already-read assistant records, with no additional source reads/schema changes.
- [X] T121 Add failing CLI tests, then expose consistent list/refresh filters and sort/order plus stats filters; validate before runtime, preserve completeness, pagination and full-source refresh scope.
- [X] T122 Add failing Pilot tests, then provide visible filter/sort controls/summary, labelled multi-source dialog with direction/reset and clickable table headers.
- [X] T123 Preserve stable row/batch selection across sort; remove invisible batch targets after filtering; verify invalid inputs, reset, refresh and existing lifecycle actions.
- [X] T124 Update README/contracts/validation, run relevant/full/packaging and SC-002 warm checks; record constitutional/privacy/compatibility self-review.
- [X] T125 Publish and merge reviewed filtering/sorting changes through GitHub, sync local main; retain independent native capability tasks T113/T117/T118.


## Phase 9: Convergence

Assessment: 2026-11-05. Findings F1–F14 cover the current implementation against the spec, plan, existing tasks and constitution. Existing tasks and completion claims above are retained unchanged. Behavioral fixes below start with an observed failing synthetic regression, then the smallest implementation and relevant checks; native runtime gates remain opt-in and use disposable histories.

- [X] T126 **CRITICAL** [F1] Закрыть небезопасный путь создания Warp launcher per Constitution IV, FR-025, T053/T058 (contradicts).
  Файлы: `src/sessions_manager/warp.py`, `tests/unit/test_warp.py`, `tests/acceptance/test_warp.py`.
  До создания ticket/config и вызова opener проверять владельца, тип, symlink и group/world-writable permissions каталога launcher и доверенность его родительского пути. Существующий owned-каталог с mode 0777 сейчас принимается. Отклонять небезопасный путь с понятной причиной, не менять права чужих существующих каталогов. Проверить writable directory/ancestor, symlink и отсутствие ticket/config/handoff при отказе; сохранить штатный приватный путь и one-shot semantics.

- [X] T127 **HIGH** [F2] Повторно сверять подтверждённый cleanup plan с актуальной полной целью непосредственно перед mutation per FR-014, FR-015, FR-019, T076/T079 (contradicts).
  Файлы: `src/sessions_manager/cleanup.py`, `tests/acceptance/test_cleanup.py`, `tests/integration/test_cleanup_recovery.py`.
  Помимо fingerprints перечисленных файлов пересчитывать поддержанный native bundle/profile и проверять неизменность полного набора артефактов; сверять сохранённый entry_digest и состояние записи при restore/purge. Новый companion после preview либо изменённая запись корзины должны требовать нового preview до первого изменения. Проверить соседей и отказ без потери данных; сохранить идемпотентное продолжение собственного durable journal после частичного выполнения.

- [X] T128 **HIGH** [F3] Согласованно обновлять общие history events и поисковые chunks всех затронутых сессий per FR-004, FR-006, FR-007, T041/T047 (contradicts).
  Файлы: `src/sessions_manager/catalog.py`, `tests/integration/test_history_catalog.py`, `tests/integration/test_search_index.py`.
  Сейчас UPSERT общего event_uid меняет отображаемую историю соседней сессии, но её индекс остаётся прежним. Различать подтверждённую ревизию общего события и конфликт идентичности; атомарно согласовывать memberships/history/search либо явно отмечать конфликт/partial, не смешивая истории молча. Покрыть копии, fork, повторный scan и изменение общего event; найденный текст должен соответствовать отображаемой истории каждой сессии.

- [X] T129 **HIGH** [F4] Изолировать повреждённые metadata/preview/history records в каждом source adapter per FR-009, FR-026, T104 (partial).
  Файлы: `src/sessions_manager/sources/claude.py`, `src/sessions_manager/sources/grok.py`, `src/sessions_manager/discovery.py` и соответствующие source contract tests.
  Воспроизвести Grok info=[] и Claude message.content=[123] рядом с корректной сессией одного root. Проверять форму данных на границе отдельной записи, сохранять доступные метаданные при отказе optional preview/history, явно отражать partial/unavailable и продолжать чтение здоровых соседей. Аналогично проверить границы остальных adapters; не маскировать отказ всего источника пустым успешным результатом и не терять cached sessions.

- [ ] T130 **HIGH** [F5] Завершить незакрытый harmless Warp runtime gate T113 per US3/AC2, FR-010, FR-011, SC-004 и plan: Warp launch decision (partial).
  Файлы: `tests/acceptance/test_warp_runtime.py`, `src/sessions_manager/warp.py`, `specs/001-session-command-center/validation.md`.
  На изолированном disposable fixture проверить реальный documented Tab Config transport, claim единственного ticket, exact argv/cwd и безвредный дочерний процесс; URI delivery не считать запуском. При воспроизведении сбоя исправлять transport под regression test. При недоступном native runtime или ограничении доступа записать точную внешнюю блокировку и сохранить явный unverified/failed outcome, не отмечать gate passing; не открывать личные AI conversations, не обходить ограничения UI и не делать автоматический повторный/new-session запуск.

  **BLOCKED 2026-11-05:** Computer Use denied access to dev.warp.Warp-Stable for safety reasons. T113/runtime remains unverified; no alternate UI/shell path was attempted.

- [X] T131 **HIGH** [F6] Согласовать resume capability с доступностью executable и объяснять исход дочернего CLI в TUI per FR-009, FR-011, US1/AC3, T056/T060 (partial).
  Файлы: `src/sessions_manager/sources/base.py`, `src/sessions_manager/launch.py`, `src/sessions_manager/ui/app.py`, `tests/contract/test_resume_commands.py`, `tests/acceptance/test_resume.py`.
  Missing/non-executable настроенный CLI не должен объявляться supported только из-за непустого executable_path; повторно проверять его перед запуском. После возврата в TUI показывать понятное сообщение для nonzero exit и interruption, сохраняя terminal state и selection. Проверить удалённый executable, отказ запуска и harmless child exits без изменения native histories и без fallback в новую сессию.

- [X] T132 **HIGH** [F7] Показывать контекст literal search match в результатах CLI/TUI per US2/AC2, FR-006, T039/T049 (missing).
  Файлы: `src/sessions_manager/catalog.py`, `src/sessions_manager/search.py`, `src/sessions_manager/cli.py`, `src/sessions_manager/ui/app.py`, `tests/integration/test_search_index.py`, `tests/acceptance/test_history.py`.
  Для совпадения только внутри сообщения вернуть ограниченный фрагмент с происхождением и вывести его вместо нерелевантного постоянного preview результата; исходный title/preview не перезаписывать. Проверить casefold с изменением длины Unicode, literal %/_, длинное сообщение, pagination и inert terminal/control text. Фрагмент должен соответствовать реально найденной истории; incomplete index остаётся явно incomplete.

- [X] T133 **HIGH** [F8] Сделать CLI overview однозначным и полным на всех страницах per FR-003, US1/AC1, T022/T031/T032 (partial).
  Файлы: `src/sessions_manager/cli.py`, `src/sessions_manager/selection.py`, `tests/contract/test_overview_cli.py`, `tests/acceptance/test_overview.py`.
  Вычислять короткие manager handles относительно всего selectable catalog до pagination/фильтрации, чтобы каждый отображённый handle однозначно разрешался тем же selector. Добавить доступные действия и явное unknown для отсутствующего title/preview без потери native ID/source/project/activity. Проверить коллизию префиксов на разных страницах/вне фильтра; полные JSON IDs сохранить.

- [X] T134 **HIGH** [F9] Сделать фактическую выборку статистики и временные границы явными per FR-020, FR-021, US5/AC4, T089/T097/T098 (partial).
  Файлы: `src/sessions_manager/statistics.py`, `src/sessions_manager/cli.py`, `src/sessions_manager/ui/app.py`, `src/sessions_manager/ui/screens.py`, `tests/unit/test_statistics.py`, `tests/acceptance/test_statistics.py`.
  Возвращать и показывать применённые source/project/model/activity/date/visibility filters и известные start/end activity range наряду с elapsed span. Предоставить явный scope choice в TUI и соблюдать его; сохранить согласованный default all, включая hidden и исключая trash. Проверить CLI/TUI scopes, unknown endpoints и выбранные sessions вне текущего overview. Сохранить lifetime-семантику выбранных сессий: фильтр последней активности не превращать в расход токенов за период.

- [X] T135 **MEDIUM** [F10] Реализовать раннюю публикацию metadata и полную provenance scan generations per plan: metadata-first/generation decisions, FR-026, T010/T012/T030/T031 (partial).
  Файлы: `src/sessions_manager/discovery.py`, `src/sessions_manager/catalog.py`, `src/sessions_manager/models.py`, `src/sessions_manager/ui/app.py`, `tests/integration/test_discovery.py`.
  Не задерживать доступный обзор до завершения history/usage всех roots. Публиковать ранние метаданные и завершённые roots с явными pending/partial/complete состояниями history/search/usage, start/finish и source revision/as_of ranges. Сохранить bounded workers, одного writer, согласованную публикацию, cancellation и cached/stale semantics. Искусственно медленный reader должен доказать ранний обзор без ложного complete поиска или статистики.

- [X] T136 **MEDIUM** [F11] Читать только подтверждённый новый JSONL tail при append per plan: source revisions/confirmed-tail decision, T047/T096 (contradicts).
  Файлы: `src/sessions_manager/sources/claude.py`, `src/sessions_manager/sources/grok.py`, `src/sessions_manager/sources/codex.py`, `src/sessions_manager/discovery.py`, `src/sessions_manager/catalog.py` и соответствующие history/usage tests.
  Сохранять проверяемую позицию ingestion и корректно объединять новые history/usage records вместо полного перечитывания изменившегося файла. При замене, усечении, несовместимой схеме или неподтверждённом префиксе безопасно пересобирать соответствующую историю. Тестами измерить границу реально прочитанных данных и проверить incomplete final record, dedup, пересборку search/ledger и unchanged-file reuse; не ослаблять SC-002.

- [X] T137 **MEDIUM** [F12] Завершить валидацию обязательных полей typed models на границах создания и десериализации per T004/T010/T070 и plan: typed value validation (partial).
  Файлы: `src/sessions_manager/models.py`, `tests/unit/test_models.py`, `tests/unit/test_cleanup_models.py`, `tests/unit/test_history_models.py`.
  Проверить недостающие enum/state, identifiers, timestamps/ranges и paths в Session, ActivityEvidence, ScanGeneration и OperationItem там, где их требует контракт; absolute path требовать только для полей с таким контрактом. Invalid presence/activity evidence сейчас принимаются. Добавить positive/negative boundary cases и безопасную обработку некорректных persisted payloads, сохраняя чтение существующих корректных private catalogs и явное unknown вместо выдуманных значений.

- [X] T138 **MEDIUM** [F13] Реализовать подтверждённые Cursor context-only metrics per FR-020, FR-022, T087/T094 (partial).
  Файлы: `src/sessions_manager/sources/cursor.py`, `tests/contract/test_cursor_usage.py`, `tests/support/cursor_factory.py`.
  Проверить поддержанную native форму usedTokens/maxTokens на synthetic fixture и при доказанных данных возвращать отдельный kind=context с provenance/completeness; unconditional not_recorded не должен скрывать известную context occupancy. Lifetime input/output/total остаются null с причиной, context нельзя суммировать как lifetime spend. Проверить известный ноль, отсутствующие/некорректные поля и unknown schema; исключить billing/network queries, token estimates, decryption и копирование секретов.

- [X] T139 **MEDIUM** [F14] Завершить проверку осуществимости scoped local Grok shared-index cleanup и restore per T117, FR-015, FR-016 и plan: bounded cleanup decision (partial).
  Файлы: `src/sessions_manager/sources/grok.py`, `tests/contract/test_grok_cleanup.py`, `tests/integration/test_cleanup_recovery.py`, `specs/001-session-command-center/research.md`, `specs/001-session-command-center/contracts/cleanup.md`.
  Сначала доказать exact target/profile/revision, принадлежность shared-index artifacts, защиту соседей и восстановление после каждого сбоя на isolated fixture. Включать mutation только для доказанного bounded reversible profile; если native primitives этого не позволяют, документировать проверенную причину блокировки и оставлять capability unavailable. Remote delete, прямые shared DB mutations и whole-DB rollback исключены. Условную Codex задачу T118 и её native cascade/recovery guard сохранить: отсутствие требуемого API не обходить.

Path clarification for T133: `short_handles` is implemented in `src/sessions_manager/models.py`; selector resolution is `Catalog.get` in `src/sessions_manager/catalog.py`. Use these existing modules in place of the mistaken `src/sessions_manager/selection.py` reference above.


## Phase 10: Convergence

Assessment: 2026-11-05. Findings F1–F6 assess the present implementation against the current spec/plan, all T001–T139 and the constitution. Existing tasks and markers above remain unchanged. Code fixes use observed failing synthetic regressions before implementation, preserve native read-only boundaries and retain SC-002 thresholds. T144 is an independent external runtime gate; T140–T143 and T145 do not depend on Warp access. T118 remains conditional, and T117/T139's documented unavailable Grok shared-index profile is retained.

- [X] T140 **CRITICAL** [F1] Закрыть пробелы в доверенности и containment файловых путей per Constitution IV, FR-025, T011/T063/T071 (contradicts).
  Файлы: `src/sessions_manager/config.py`, `src/sessions_manager/fsops.py`, `tests/unit/test_config.py`, `tests/contract/test_cleanup_protocol.py` и filesystem boundary tests T063.
  `ensure_private` сейчас принимает приватный leaf, не проверяя возможность подмены через его родителей; `secure_path` принимает lexical `source/../neighbor` вне разрешённого root. До создания/открытия manager data, копирования и rename проверять доверенную ancestry, владельцев, writable parents, symlinks и фактическую разрешённую границу. Не менять права существующих пользовательских каталогов и не обходить проверки простой нормализацией строки. Сохранить поддержку безопасных macOS paths/проверенных platform aliases и root-owned sticky parents через явно проверенную привязку. Регрессии должны доказать отказ для 0700 leaf под небезопасным parent, подмены пути и dot-dot escape до первого изменения, а также отсутствие затрагивания соседей.

- [X] T141 **HIGH** [F2] Отделить успешную пустую enumeration от отсутствующего/недоступного root и изолировать ошибки JSONL projection per US1/AC2, FR-009/026, T020/T030/T129/T135 (partial).
  Файлы: `src/sessions_manager/discovery.py`, `src/sessions_manager/sources/base.py`, `src/sessions_manager/sources/jsonl_cursor.py`, source adapters и соответствующие contract/integration tests.
  На fresh cache все четыре reader сейчас объявляют missing root complete/0; подавленный glob-ошибкой PermissionError также становится complete empty. Проверять реальный исход enumeration, возвращать отдельную причину и сохранять cached sessions/as_of без ложного missing. Ограничить глубину/объём recursive checkpoint projection: поддерживаемый JSON с глубоко вложенным content сейчас вызывает RecursionError, который выходит из reader/coordinator и прерывает общий refresh. Повреждённую запись изолировать, доступные метаданные и здоровые соседние сессии/roots сохранять; worker failure не выдавать за полный результат. Проверить отсутствующий root, denied listing, nested content, partial/cancel и отсутствие утечки содержимого в diagnostics; не поглощать пользовательское прерывание как успешный scan.

- [X] T142 **HIGH** [F3] Согласовывать известные alias identities между фазами refresh до выдачи resume/cleanup capabilities per FR-004/009/026, T030/T128/T135 и plan: identity/publication decisions (contradicts).
  Файлы: `src/sessions_manager/discovery.py`, `src/sessions_manager/catalog.py`, `src/sessions_manager/launch.py`, `tests/integration/test_discovery.py`, `tests/integration/test_history_catalog.py` и resume/cleanup boundary tests.
  Metadata-фаза не переносит полный контекст alias roots; первая законченная копия может получить supported resume при ещё scan_pending другой известной копии того же namespace/native ID. Не очищать прежние conflict/evidence guards и не выбирать доверенную копию до требуемого согласования. Доступный metadata/history snapshot можно публиковать как partial; опасные действия должны иметь явную unverified/conflict причину до доказательства identity. Проверить обе последовательности завершения roots, одинаковые/различные копии, warm refresh и ошибку/отмену второго root после metadata; реальный launch/cleanup не должен обходить guard повторным чтением только одного root. Сохранить bounded workers и ранний обзор.

- [X] T143 **HIGH** [F4] Привязать purge-derived cleanup и tombstone reconciliation к актуальному lifecycle выбранной записи per FR-004/018/026, T030/T080/T136 (contradicts).
  Файлы: `src/sessions_manager/cleanup.py`, `src/sessions_manager/catalog.py`, `tests/integration/test_cleanup_recovery.py`, `tests/integration/test_discovery.py` и cleanup acceptance tests.
  После trash→restore→trash purge старого restored-entry сейчас проверяет только sessions.presence='trashed' и удаляет кеш более нового entry, переводя всю сессию в purged. Очистка старой копии должна затрагивать только подтверждённую копию и принадлежащие ей derived данные; новый trash/native lifecycle сохраняется. При доказанном повторном появлении исходной истории обновлять доступность с сохранением стабильного manager ID и hidden state: безусловное сохранение прежнего trashed/purged сейчас скрывает реально найденную историю из list/stats. Не реактивировать запись по stale projection или одному cached заголовку. Покрыть несколько lifecycle циклов, старый backup плюс новый trash, внешнее восстановление/появление source, cached history/search/parser checkpoint и сохранность соседних entries; существующий restore conflict/no-overwrite guard сохранить.

- [ ] T144 **HIGH** [P] [F5] Завершить оставшийся native Warp runtime gate после появления разрешённого доступа per US3/AC2, FR-010/011, SC-004, T113/T130 и plan: validation gate 3 (partial).
  Файлы: `tests/acceptance/test_warp_runtime.py`, `src/sessions_manager/warp.py`, `specs/001-session-command-center/validation.md`.
  Текущий подтверждённый внешний блок — Computer Use denial для dev.warp.Warp-Stable; этот проход его не обходил и native runtime не запускал. До изменения ограничения сохранять unverified/blocked, не отмечать T113/T130 или этот gate passing. После разрешённого доступа использовать disposable histories и harmless child, проверить claim единственного ticket и записанные exact argv/cwd/exit, а не только URI delivery или существование ack. Исправление воспроизведённого transport сбоя начинать с regression test. Не открывать личные AI conversations, не обходить запрет альтернативным UI/shell путём и не запускать автоматически повторный/new-session процесс.

- [X] T145 **MEDIUM** [F6] Завершать interrupted purge согласованно с уже сохранённым terminal receipt per FR-019, T068/T078/T080 (partial).
  Файлы: `src/sessions_manager/cleanup.py`, `src/sessions_manager/fsops.py`, `tests/integration/test_cleanup_recovery.py`.
  Purged receipt коммитится до удаления последнего entry directory. Если remove_owned_tree удалил directory/manifest, но последующий fsync завершился ошибкой, общий exception handler меняет purged на recovery_required; повтор затем требует отсутствующий manifest и остаётся в recovery_required. Сохранить истинный durable outcome и отдельно согласовывать завершающую уборку, не понижая committed purge до невосстановимого состояния. Проверить crash после receipt до удаления directory, ошибку после удаления manifest/directory, частично завершённый terminal cleanup и повтор по тому же op_id после рестарта. Остатки удалять только в исходной подтверждённой manager-owned области, без нового source scope, потери соседей или ложного сообщения об оставшемся recoverable payload.


## Phase 11: Native Codex Archive / Unarchive

User-approved 2026-11-05; FR-028. Independent of blocked Warp and conditional T118.

- [X] T146 Document the separate archive contract and verify installed 0.166.0 native cascade/unarchive on a fresh offline fixture: parent, two descendants including pre-archived, unrelated neighbor; exact history/ID preservation.
- [X] T147 Write failing native archived-metadata/catalog/active-overview regressions, then retain archived flags and separate active vs archive listings without changing manager hide/presence.
- [X] T148 Write failing preview/confirmation/closed-set/graph/activity/alias/recovery tests, then implement bounded native RPC archive coordinator and durable same-scope retry/unarchive prestates. No direct native DB writes in application code.
- [X] T149 Write failing CLI and Textual Pilot regressions, then add separate Archive / Archived / Unarchive actions, exact preview, closed assertion, partial/retry results and human explanations.
- [X] T150 Update docs/validation, run full/Ruff/package/SC-002 gates, record self-review and publish/merge the authorized GitHub PR. Retain all existing native cleanup/Warp limits.


## Phase 12: Convergence

Assessment: 2026-11-06. Findings F1–F6 assess the current implementation against spec.md, plan.md, all T001–T150 and the constitution; existing text/checkmarks above remain unchanged. Read-only inspection and synthetic in-memory probes confirmed the gaps below; no pytest, native mutation, personal-history operation or Warp runtime was run during this assessment. Behavioral fixes require observed failing regressions before implementation, boundary coverage and updated validation/docs, followed by relevant/full/Ruff/package checks and unchanged SC-002 thresholds. T154 is an independent external gate and does not block T151–T153/T155–T156. Conditional Codex cleanup T118 and the documented unavailable Grok shared-index cleanup remain unchanged; native archive does not satisfy their gates.

- [X] T151 **CRITICAL** [F1] Защитить trash/purge/restore lifecycle и derived retention от устаревших reader publications per Constitution IV, FR-004/018/019/026, T030/T080/T136/T143 и plan: lifecycle/publication decisions (contradicts).
  Файлы: `src/sessions_manager/catalog.py`, `src/sessions_manager/cleanup.py`, `src/sessions_manager/discovery.py`, `tests/integration/test_cleanup_recovery.py`, `tests/integration/test_discovery.py`.
  `Catalog.publish` разрешает любому прежнему full scan с `_native_history_verified=True` вернуть tombstone в present; `_save_session` затем очищает current_trash_id, а history/usage/cursor публикация может повторно сохранить очищенные данные. Подтверждено в памяти для обоих состояний trashed/purged: результат reader, завершённого до mutation, восстанавливает present и cached event. Связать публикацию с durable актуальным lifecycle/revision и проверять его в той же writer transaction; stale metadata/full/history/search/usage/checkpoint результаты не должны менять новое состояние, ownership или восстанавливать purged cache. Сохранить корректное обнаружение доказанно нового native reappearance после mutation, стабильные ID/hidden и существующие alias/archive guards. Сначала воспроизвести reader-finished-before-trash/purge-published-after, несколько lifecycle циклов, restore и отдельные CLI processes; проверить restart, сохранность соседей и отсутствие ложного complete/as_of. Не решать гонку безусловным запретом внешнего восстановления или одним process-local lock.

- [X] T152 **CRITICAL** [F2] Проверять доверенную ancestry отсутствующих Codex rollout references до native Archive/Unarchive per Constitution IV, FR-025/028, T140/T148 и plan: trusted paths/native archive decisions (contradicts).
  Файлы: `src/sessions_manager/native_archive.py`, `src/sessions_manager/fsops.py`, `tests/integration/test_native_archive.py` и filesystem boundary tests.
  В `native_snapshot` отсутствующий rollout проходит только lexical containment и leaf is_symlink; `fsops.inventory/secure_path` для него не вызывается. Существующий symlink/writable/foreign-owned parent или non-directory component остаётся непроверенным перед native RPC. Проверять разрешённую границу и все существующие компоненты ancestry даже при отсутствующем leaf; при невозможности доказательства отказывать до первого RPC. Связать допустимую reference/existence evidence с preview/revalidation, чтобы смена привязки не проходила как прежний snapshot. Не создавать rollout/каталоги, не chmod пользовательские paths и не разыменовывать недоверенный alias как разрешение. Сначала воспроизвести missing leaf под symlink наружу, небезопасным parent, файлом вместо directory, а также подмену между preview/commit; доказать отсутствие native вызова и изменения соседей. Сохранить поддержку проверенных paginated histories без rollout, безопасных отсутствующих references и root-controlled platform aliases.

- [X] T153 **HIGH** [F3] Изолировать ошибки открытия списка native archives в TUI per FR-009/026, SC-008, T115/T149 (partial).
  Файлы: `src/sessions_manager/ui/app.py`, `src/sessions_manager/ui/screens.py`, `tests/acceptance/test_native_archive.py`, `tests/unit/test_human_errors.py`.
  `action_archives` создаёт ArchiveService и вызывает list() вне Failure handler; синтетический archive_journal_invalid выходит наружу, экран объяснения не появляется. Обработать ожидаемые ошибки создания service/чтения списка тем же безопасным human explanation контрактом, сохранить overview и работу здоровых источников; повреждённый журнал не удалять, не исправлять молча и не интерпретировать как пустой archive. Сначала получить падающий Textual Pilot regression для открытия Archives с повреждённым persisted operation и для отказа service initialization; проверить понятное сообщение без содержимого/traceback, возможность вернуться к обычным сессиям и отсутствие native RPC. Сохранить стабильные JSON failure codes и уже работающие preview/confirm/retry guards.

- [ ] T154 **HIGH** [P] [F4] Завершить оставшийся harmless native Warp runtime gate только после появления разрешённого доступа per US3/AC2, FR-010/011, SC-004, T113/T130/T144 и plan: validation gate 3 (partial).
  Файлы: `tests/acceptance/test_warp_runtime.py`, `src/sessions_manager/warp.py`, `specs/001-session-command-center/validation.md`.
  Ранее URI был доставлен, но ticket не был claimed; остаётся внешний запрет: Computer Use is not allowed to use the app 'dev.warp.Warp-Stable' for safety reasons. Этот аудит runtime не запускал. Пока ограничение действует, сохранять blocked/unverified и не отмечать gate passing; не обходить запрет альтернативным shell/UI способом. После разрешённого доступа использовать disposable synthetic histories и harmless child, проверить single claim, exact argv/cwd/exit и подтверждённый handoff, а не только URI/ack. Воспроизведённое исправление transport начинать с failing regression. Не открывать личные AI conversations и не добавлять автоматический повтор/new-session fallback. Эта задача независима от остальных исправлений Phase 12.

- [X] T155 **MEDIUM** [F5] Показывать общий объём shared source storage отдельно от per-session bytes per spec: shared-storage-size edge case, FR-020/023, US5/AC1, T089/T097/T098 (partial).
  Файлы: `src/sessions_manager/statistics.py`, `src/sessions_manager/catalog.py`, `src/sessions_manager/discovery.py`, source adapters, `src/sessions_manager/cli.py`, `src/sessions_manager/ui/screens.py` и statistics contract/acceptance tests.
  Сейчас summarize/_other_metrics выдаёт только known_session_bytes; отдельной source storage метрики нет, в том числе для общих Codex DB, размер которых нельзя приписать одной сессии. Сначала воспроизвести отсутствие отдельного показателя на synthetic shared store. Добавить read-only измерение и manager provenance/coverage/as_of для доказанного source-level объёма в рамках configured roots, с отдельным отображением CLI/TUI/JSON и явной семантикой при выборе одной сессии/проекта. Shared bytes не включать в per-session sum, не умножать на число сессий/aliases, не считать unknown нулём и не обещать столько освобождённого места. Проверить несколько сессий одного DB, повторные/overlapping roots, известный ноль, denied/missing/partial/stale source и фильтры; не вводить full-computer scan или новый обязательный дорогой обход на каждое открытие stats. Обновить docs/contracts и сохранить SC-002 budgets.

- [X] T156 **LOW** [F6] Сохранять и показывать неоднозначность native dates без timezone per spec: timezone edge case, FR-003, SC-001, T010/T025–T028 (partial).
  Файлы: `src/sessions_manager/models.py`, source adapters, `src/sessions_manager/cli.py`, `src/sessions_manager/ui/screens.py`, metadata/date/filter/statistics tests.
  `timestamp` возвращает None для naive ISO, а Session/adapters оставляют timezone_confidence='known'; synthetic Claude record с timestamp 2026-11-01T12:30:00 получает именно эту комбинацию. Отличать отсутствующее/невалидное время от записанной даты без достоверного пояса и выводить понятный ambiguous reason в деталях/JSON, не назначая локальный или UTC пояс догадкой. Сначала написать падающие metadata/presentation regressions для naive, aware, absent и mixed timestamps; не терять достоверные aware границы из-за другой неоднозначной даты и не включать naive значения в UTC period filters/сводные интервалы. Сохранить unknown-last sorting, локальный пояс для доказанных дат и отсутствие новых source writes; совместимость manager payload и пользовательское объяснение документировать.


## Phase 13: Convergence

Assessment: 2026-11-06. Findings F1–F5 assess the present implementation against spec.md, plan.md, all T001–T156 and the constitution. Existing content/checkmarks above remain unchanged. Source inspection and synthetic in-memory probes confirmed the gaps below; this audit ran no pytest/native mutation/personal-history operation/Warp runtime and used no git/history comparison. Behavioral fixes require observed failing regressions before implementation, relevant boundary tests, docs/validation and unchanged full/Ruff/package/SC-002 gates. T159 is an independent external gate and does not block T157/T158/T160/T161. Conditional Codex cleanup T118 and unavailable Grok shared-index cleanup remain unchanged; unverified Codex 0.167.0 is outside the current FR-028 profile, not an instruction to enable a new native version.

- [X] T157 **CRITICAL** [F1] Согласовывать все физические locations одной identity, включая несколько копий внутри одного root, до публикации истории и выбора cleanup target per Constitution IV, FR-004/009/014/015/026, T030/T128/T142 и plan: identity/publication decisions (contradicts).
  Файлы: `src/sessions_manager/discovery.py`, `src/sessions_manager/catalog.py`, `src/sessions_manager/cleanup.py`, `src/sessions_manager/launch.py`, source adapters и identity/history/cleanup boundary tests.
  Сейчас compare_identity и catalog alias reconciliation включаются только при нескольких configured root IDs; две Claude projects/*/same.jsonl внутри одного root получают один UID без conflict. History/usage maps по одному UID теряют различие копий до проверки. В подтверждённом in-memory сценарии каталог показывает cwd/locator B и root complete, а CleanupService._snapshot через next(discover...) подставляет artifact A. Рассматривать location как root + locator, сохранять доказательства каждой копии до согласования и не выбирать произвольную историю/проект. Неоднозначные копии должны явно блокировать resume/cleanup и не публиковать конфликтующее content/usage как complete; идентичные aliases не должны дублировать строку. Cleanup требует единственной доказанной location, а revalidation обязана совпадать с показанной location/fingerprint/identity, не только native ID. Сначала воспроизвести metadata/full/warm refresh для одинаковых/различающихся копий в одном root, обе последовательности, смену порядка enumeration, появление/исчезновение копии и конфликт cwd/history/graph. Проверить согласованность CLI/TUI details/search/stats и точное соответствие выбранной сессии preview; ни confirm, ни restart/retry не должны затронуть другую физическую копию. Сохранить межкорневые guards, stable IDs/hidden, lifecycle/native-archive fences, bounded workers и SC-002.

- [X] T158 **HIGH** [F2] Сделать незавершённую cleanup operation доступной для восстановления даже до появления TrashEntry per FR-019/026, US4/AC6, T068/T078/T082/T151 и plan: durable lifecycle recovery (partial).
  Файлы: `src/sessions_manager/cleanup.py`, `src/sessions_manager/catalog.py`, `src/sessions_manager/cli.py`, `src/sessions_manager/ui/screens.py`, `tests/integration/test_cleanup_recovery.py` и cleanup CLI/Pilot acceptance tests.
  Commit сохраняет operation/item и lifecycle_pending перед _trash; прерывание в первой проверке/до _begin_entry оставляет owner, блокирующий Open и новый cleanup. Но trash_list читает только trash_entries: подтверждённый probe оставляет одну journaled operation/item и пустой recovery list, без доступного пользователю исходного op_id. Показывать такие pending операции и их точный stage/targets в CLI/TUI с повтором исходного op_id после перезапуска; не изображать ещё не созданную recoverable copy как готовую корзину и не создавать новый scope/дубликат. Также согласовать видимые retry actions при terminal receipt/item, если crash оставил lifecycle owner до finish_lifecycle. Сначала воспроизвести остановку после durable owner до entry/manifest, на границе создания entry и между сохранением terminal item и снятием owner; закрыть/reopen каталог и выполнить доступный через CLI/TUI same-operation retry. Проверить batch/per-item исходы, closed assertion, неизменность source/соседей, отсутствие generic unlock/удаления журнала и корректное снятие owner только после доказанного результата. Существующие conflict/no-overwrite и purge cleanup_pending гарантии сохранить.

- [ ] T159 **HIGH** [P] [F3] Завершить оставшийся harmless native Warp runtime gate только после появления разрешённого доступа per US3/AC2, FR-010/011, SC-004, T113/T130/T144/T154 и plan: validation gate 3 (partial).
  Файлы: `tests/acceptance/test_warp_runtime.py`, `src/sessions_manager/warp.py`, `specs/001-session-command-center/validation.md`.
  Сохраняется ранее подтверждённый внешний блок: Computer Use is not allowed to use the app 'dev.warp.Warp-Stable' for safety reasons. Этот аудит не запускал runtime и не обходил запрет альтернативным shell/UI способом. Пока ограничение действует, оставлять gate blocked/unverified, а не passing. После разрешённого доступа использовать disposable synthetic histories и harmless child, доказать один claim ticket и exact argv/cwd/exit/handoff; URI delivery или ack не доказывают открытие разговора. Любое воспроизведённое исправление transport начать с failing regression. Личные AI conversations и автоматический повтор/new-session fallback исключены. Эта задача независима от остальных исправлений Phase 13.

- [X] T160 **MEDIUM** [F4] Исключить следование по промежуточным symlinks при fallback измерении source storage per T155, FR-023/024/026, spec: shared-storage/permission edge cases и plan: bounded no-follow storage decision (partial).
  Файлы: `src/sessions_manager/storage.py`, `src/sessions_manager/sources/base.py`, `tests/integration/test_source_storage.py` и соответствующие source discovery boundary tests.
  При explicit narrow Cursor/Grok root без chats/sessions measure получает session directories через discover_paths('*/*/store.db' или summary.json). Этот helper вызывает entry.is_dir() с follow_symlinks=True; visit затем проверяет leaf directory, пропуская symlink среди родителей. In-memory filesystem probe подтвердил переход по link, включение внешнего файла 73 bytes и complete=True. Соблюдать разрешённую границу и no-follow для всех компонентов обхода, включая fallback; matched unsafe/denied links должны давать явную partial/unknown причину, а не достоверный empty zero. Не разыменовывать ссылку нормализацией как разрешение на новый subtree. Сначала воспроизвести реальный synthetic symlink workspace/session наружу, dangling link, intermediate substitution и недоступный parent; доказать, что внешний sentinel/поддерево не перечисляются и не входят в complete bytes. Сохранить явно настроенные допустимые root bindings, dedup пересекающихся roots, cached as_of/coverage, отсутствие stats-open I/O/native writes и SC-002 budgets. Если меняется общий discover_paths, проверить здоровые source readers и ранний metadata обзор.

- [X] T161 **MEDIUM** [F5] Валидировать форму source configuration и boolean flags до интерпретации области сканирования per T005/T009/T010/T011, FR-006 и plan: typed source/config boundaries (partial).
  Файлы: `src/sessions_manager/config.py`, `src/sessions_manager/models.py`, `tests/unit/test_config.py`, `tests/unit/test_models.py` и CLI error-contract tests.
  Валидный TOML с sources=1 сейчас вызывает необработанный Config.load TypeError и общий internal_error вместо invalid_config; enabled="false" сохраняется строкой в SourceRoot и считается включённым по truthiness. Проверять ожидаемую форму sources/каждого source и точные типы управляющих enabled/default_root на соответствующих constructor/deserialization/config границах; не преобразовывать строки/числа молча в boolean. Сначала воспроизвести scalar/map/null-like malformed shapes, строковые/числовые flags и корректные true/false. Ошибка конфигурации должна иметь существующий безопасный invalid_config/exit 2 контракт без содержимого config, до открытия каталога/сканирования/создания runtime state; корректный enabled=false исключает root из refresh и сохраняет неизменными его generation/as_of. Сохранить валидные существующие configs, defaults/explicit replacements, namespaces/native context и отсутствие credentials в persisted config/diagnostics. Не вводить новый формат конфигурации или новые native capabilities.


## Phase 14: Convergence

Assessment: 2026-11-06. Findings F1–F6 assess the present code against spec.md, plan.md, all T001–T161 and the constitution. Existing tasks/markers remain unchanged. Source inspection, mocked native-reader/UI probes and an in-memory SQLite catalog reproduced F1–F5 without filesystem fixtures, pytest, native CLI launches, personal-history access or git/history comparison. This is audit evidence, not the required RED-to-GREEN implementation tests. Coverage: 28 FR, 7 buildable SC (SC-003 remains the separate owner usability measurement), 27 base acceptance scenarios plus filtering/archive amendments, 24 grouped plan obligations and 5 constitutional principles. Behavioral fixes start with observed failing synthetic regressions, then relevant boundary/full/Ruff/package/unchanged SC-002 checks and documentation/validation. T167 retains the independent externally blocked Warp gate and separates remaining native current-terminal acceptance; it does not block T162–T166. Conditional Codex cleanup T118 and unavailable Grok shared-index cleanup remain unchanged. FR-028 still covers verified Codex 0.166.0 only; this phase does not authorize enabling 0.167.0 or another native profile.

- [X] T162 **CRITICAL** [F1] Сохранять физическую location в собственном history cache Cursor до общей alias reconciliation per Constitution IV, FR-004/007/009/026, T037/T045/T128/T157 и plan: per-location identity/publication decisions (contradicts).
  Файлы: `src/sessions_manager/sources/cursor.py`, `src/sessions_manager/discovery.py`, `tests/contract/test_cursor_history.py`, `tests/integration/test_local_aliases.py` и соответствующие CLI/Pilot boundary tests.
  Adapter._discover_one сохраняет graph в _history[agentId], а read_history читает по session.native_id. Поэтому две принятые locations одного root с тем же native ID теряют различие ещё до исправленных per-location scan maps: in-memory probe для A=alpha/B=beta вернул beta для обеих копий. При одинаковом cwd обе получают одинаковый digest и могут выглядеть согласованными. Ключевать native-reader evidence по root/locator либо передавать его с конкретной сессией; не выбирать последний завершившийся reader. Проверить остальные adapter-local caches на ту же потерю физической привязки. Сначала написать и наблюдать падающие реальные synthetic Cursor-store regressions для одинаковых/различающихся графов в одном root, обеих последовательностей и thread completion order, metadata/full/warm refresh и pickled worker transport. Доказать явный conflict без произвольных details/search/usage/resume, одну строку для истинных aliases, стабильность UID/hidden и безопасное исчезновение копии. Сохранить bounded readers, partial unknown-node semantics, native read-only границы, cleanup single-location guard и SC-002.

- [X] T163 **HIGH** [F2] Привязать Open dialog и повтор manual-guide к исходному выбранному UID per FR-004/010/011/012, US2/AC4, US3/AC1, T048/T052/T060/T123 и plan: stable selection/exact resume decisions (contradicts).
  Файлы: `src/sessions_manager/ui/app.py`, `src/sessions_manager/ui/screens.py`, `tests/acceptance/test_resume.py`, `tests/acceptance/test_filters_sorting.py`.
  action_resume показывает cwd выбранной A, но callback _resume_choice вызывает resume_selected, который заново берёт selected_uid. Если refresh завершился при открытом modal и A исчезла из списка, reload_rows выбирает соседнюю B. In-memory callback probe подтвердил построение LaunchRequest для B после открытия диалога для A. Сохранить исходный stable UID и показываемую привязку на всё время выбора терминала/cwd и повторов после manual guide; перед handoff перепроверять именно её. Изменившаяся, пропавшая или недоступная A должна дать отказ/обновление выбора, без запуска B, latest или новой сессии. Сначала воспроизвести реальным Pilot диалог Open во время завершения refresh с удалением/исключением A; проверить current и mocked Warp, смену порядка/фильтра, retry guide и Cancel. Проверить отсутствие child/ticket для соседней сессии, точные ID/cwd для сохранившейся A и штатный suspend/return. Не ослаблять существующую native revalidation.

- [X] T164 **HIGH** [F3] Согласовывать usage evidence всех физических aliases независимо от совпадения истории per FR-009/020/022/026, SC-005, T091–T096/T128/T142/T157 и plan: unique usage facts/snapshot coverage decisions (contradicts).
  Файлы: `src/sessions_manager/discovery.py`, `src/sessions_manager/catalog.py`, `src/sessions_manager/statistics.py`, `tests/integration/test_local_aliases.py`, `tests/integration/test_usage_catalog.py`, `tests/unit/test_statistics.py` и stats CLI/Pilot tests.
  identity_digest сравнивает cwd/events/graph, но не usage. Catalog.publish выбирает usage одной representative location; per-location данные другой копии не участвуют в проверке. In-memory catalog с одинаковой history proof и Grok snapshots одного native scope 10/999 опубликовал total_tokens=10, usage_state=complete и metric.complete=true без причины конфликта. Сохранять/сверять native receipt/snapshot scope/revision и completeness каждой копии до объявления суммы достоверной. Использовать доказанную native reconciliation, где она предусмотрена, либо явную partial/conflict/non-summable semantics; не выбирать расход по имени пути/порядку завершения и не складывать копии. Различие usage само по себе не должно лишать доступной согласованной истории вопреки per-capability isolation. Сначала воспроизвести same-root и cross-root matching/conflicting usage, смену enumeration/publication order, warm cache, failed/unknown peer, исчезновение копии и разрешение конфликта. Покрыть Claude monotonic receipts, Codex fact ownership и Grok snapshots; Cursor context observations остаются отдельно от lifetime spend. Проверить CLI/TUI/JSON known-zero/unknown/coverage, отсутствие произвольного complete и сохранность native data, stable IDs и SC-002.

- [X] T165 **HIGH** [F4] Изолировать ошибки открытия корзины и recovery listing в TUI per FR-009/019/025/026, US4/AC6, SC-008, T082/T115/T153/T158 и plan: recovery/error isolation decisions (partial).
  Файлы: `src/sessions_manager/ui/app.py`, `src/sessions_manager/cleanup.py`, `src/sessions_manager/ui/screens.py`, `tests/acceptance/test_cleanup.py`, `tests/integration/test_cleanup_recovery.py`.
  action_trash создаёт CleanupService и вызывает trash_list вне try. В отличие от Archives обработчик не удерживает Failure/OSError/SQLite errors; in-memory probes подтвердили выход unsafe_directory_path при initialization и catalog_record_invalid при listing за границу UI handler. Повреждённые persisted JSON также не должны приводить к необработанному выходу TUI или выводу содержимого журнала. Показать безопасное actionable объяснение, сохранить journal/manifest/payload и возможность вернуться к здоровому overview; не ремонтировать и не удалять recovery state автоматически. Сначала добавить падающие Pilot scenarios для initialization failure, denied/missing manager trash и malformed operation/trash listing, затем проверить отсутствие native mutation/потери journal, сохранение selection и работу деталей/refresh после отказа. Сохранить CLI stable error codes, same-operation retry и различие pending operation от recoverable copy. Не скрывать ошибку ложным пустым успешным списком.

- [X] T166 **HIGH** [F5] Сделать reconstruction Grok ACP идемпотентной по доказанной packet identity per FR-004/006/007/026, SC-001/005, T033/T036/T041/T044/T047 и plan: native event identity/history normalization decisions (contradicts).
  Файлы: `src/sessions_manager/sources/grok.py`, `src/sessions_manager/sources/jsonl_cursor.py`, `tests/contract/test_grok_history.py`, `tests/integration/test_history_catalog.py` и history/search/usage acceptance tests.
  read_history различает message/prompt grouping, но повтор одного eventId/messageId безусловно выполняет events[key].text += content['text']. In-memory probe двух одинаковых packets packet-once/message-once вернул SYNTHETIC-ONCESYNTHETIC-ONCE со state=complete. Повтор той же доказанной native packet не должен повторно добавлять delta; конфликтующий payload того же packet ID должен явно снижать полноту, а не молча заменять/склеивать содержание. Сохранить законные одинаковые text chunks с разными packet IDs, message/prompt boundaries и существующую partial fallback при отсутствии доказанных IDs. Сначала написать падающие fixtures для repeated packet подряд/через другие события, conflicting duplicate, legitimate repeated text, tool updates и confirmed-tail/warm replay. Проверить порядок истории, точный literal search, logical message/tool counts и отсутствие повторного usage; повреждение одной записи не скрывает здоровые соседние сессии. Никаких native writes/remote calls или новых guessed formats.

- [ ] T167 **HIGH** [P] [F6] Завершить оставшиеся native resume acceptance gates с отдельным учётом blocked Warp per US3/AC1–AC2, FR-010/011/012, SC-004, T051–T054/T112/T113/T130/T144/T154/T159 и plan: validation gate 3/exact native binding decision (partial).
  Файлы: `tests/acceptance/test_resume.py`, `tests/acceptance/test_warp_runtime.py`, `tests/support/native_resolver.py`, disposable native-fixture support и `specs/001-session-command-center/validation.md`.
  Synthetic argv/resolver checks и доказанный actual Codex 0.166.0 current-terminal fixture не подтверждают end-to-end native current-terminal conversation binding для Claude/Grok/Cursor; validation.md сохраняет эти проверки unperformed. Отделить проверку native ID/context/cwd каждой поддержанной CLI от harmless Warp transport gate. Добавить/завершить явные opt-in проверки только с disposable artificial histories, exact recorded conversation/ID/cwd, отсутствием новой сессии и сохранностью соседей; один argv, process exit, URI delivery или ack недостаточен. Если безопасный изолированный fixture/profile не доказан, явно сохранить unverified и документировать проверенное ограничение, без личных conversations/credentials, AI turns, remote calls или fallback/new-session. Warp остаётся независимо blocked прежним запретом: Computer Use is not allowed to use the app 'dev.warp.Warp-Stable' for safety reasons. Не запускать его и не обходить запрет альтернативным shell/UI путём; продолжить native Warp gate только после разрешённого доступа с одним claim ticket и exact argv/cwd/exit/handoff. Воспроизведённые transport/binding исправления начинать с failing regression. Не отмечать исходные Warp gates passing; не расширять Codex 0.167.0/archive или условную cleanup T118.

Phase 14 implementation status (2026-11-06): T162–T166 completed with observed RED-to-GREEN evidence, docs, full/Ruff/package and unchanged SC-002 gates. T167 is partially implemented: explicit isolated native current-terminal opt-ins plus containment/exact-version checks exist, but Claude/Grok/Cursor did not prove conversation loading under the required offline/private boundaries. The explicit three-provider run remains FAIL/unverified, not passing. Warp remains externally blocked and was not accessed. See validation.md; no native capability/version expansion or personal-store fallback was enabled.
