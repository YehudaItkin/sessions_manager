# Implementation Plan: Единый CLI-центр AI-сессий

**Branch**: `001-session-command-center` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-session-command-center/spec.md`

## Summary

Создать локальную команду `sessions`: без аргументов — интерактивный обзор, с подкомандами —
поиск/детали, точное native resume, manager-only скрытие, безопасная корзина и статистика.
Один Python-пакет; native данные читают четыре versioned adapters, собственный SQLite
хранит приватный каталог/поиск/состояния. Никакого сервера, AI-запросов или cloud sync.

Phase 0 завершена: [research.md](research.md). Реальные профили существенно различаются:
Codex использует shared paginated projections; Claude и Codex повторяют usage evidence;
Grok хранит ACP/native files; Cursor — локальный JSON/protobuf-граф.
У Codex 0.166.0 source cleanup отключена из-за неограниченного native cascade.
Cursor lifetime tokens остаются unknown; context occupancy не подменяет расход.

Phase 1 завершена: [data-model.md](data-model.md), [contracts](contracts/cli.md),
[quickstart.md](quickstart.md). Это дизайн, не реализация или заявление о прохождении runtime gates.

## Technical Context

**Language/Version**: Python >=3.12; текущая исследованная среда Python 3.14.8.
Нативные SDK или выполнение кода других инструментов для чтения не требуются.

**Primary Dependencies**: Typer (scriptable commands), Textual (overview/Pilot/suspend),
Rich (table output), tomli-w (Warp TOML). Stdlib для SQLite, typed dataclasses, JSON,
filesystem, processes, hashing и timezone. Exact versions фиксируются uv.lock при реализации.

**Storage**: Приватный SQLite catalog с FTS5 trigram/external content; config.toml,
trash manifests/payload и одноразовые launch manifests в user Application Support.
Исходные JSONL/SQLite/blob stores остаются собственностью native CLI.

**Testing**: Обязательный TDD; pytest, pytest-asyncio, Typer CliRunner, Textual Pilot;
синтетические JSONL/SQLite/WAL/protobuf fixtures и child executables. Ruff — lint/format.
Fault injection и source-neighbor invariants важнее формального процента coverage.

**Target Platform**: macOS текущего пользователя, проверенная локальная arm64-среда;
терминал и установленная Warp. Другие ОС, Cursor IDE и ACP profiles вне первой версии.

**Project Type**: Локальное CLI/TUI-приложение, один пакет, без фонового демона.

**Performance Goals**: SC-002: 10 000 сессий / до 1 ГиБ; cold discovery/readiness <=10 с;
warm meaningful overview, search и navigation <=2 с на целевой машине.
Это обязательный будущий benchmark gate; измеренного результата приложения пока нет.

**Constraints**: Offline read-only discovery/history/search/statistics; отсутствие
native repair/credentials extraction; literal Unicode search; explicit completeness;
safe foreground handoff; mutation только по проверенному source profile и подтверждённому
manifest. Нет generic force, native cloud delete или whole shared-DB rollback.

**Scale/Scope**: Один владелец, четыре CLI, несколько явно заданных локальных roots;
missing/unsupported форматы изолированы. No-arg overview не требует ручного экспорта истории.

## Constitution Check

*GATE: проверено до Phase 0 и повторно после Phase 1.*

| Принцип / требование | До исследования | После дизайна | Доказательство |
| -------------------- | --------------- | ------------- | -------------- |
| I. Clear Requirements | PASS | PASS | 5 user stories, FR-001–FR-027, SC-001–SC-008; traceability ниже |
| II. Simple Design | PASS | PASS | Один пакет/процесс/catalog; 4 нужные runtime libs, без ORM/server/AI SDK |
| III. TDD | PASS | PASS | Red-before-implementation, synthetic fixtures, boundary/fault tests |
| IV. Protected Session Data | PASS | PASS | Private state, inert text, no scan network, capability-gated cleanup/journal |
| V. Documented Changes | PASS | PASS | Source/version matrix, CLI/launch/cleanup contracts, validation guide |
| GitHub / review | PASS | PASS | YehudaItkin/sessions_manager; feature branch; будущая публикация через PR |

Неподдержанная cleanup Codex соответствует FR-009/FR-016 и shared-store edge case;
она не объявляется успешной реализацией удаления. Для остальных sources mutation включается
только после safety gates, не по одному факту чтения истории. Исключений из конституции нет.
Неизвестных продуктовых решений и незавершённых вопросов Technical Context не осталось.

## Project Structure

### Documentation (this feature)

```text
specs/001-session-command-center/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
└── contracts/
    ├── cli.md
    ├── sources.md
    ├── launch.md
    └── cleanup.md
```

tasks.md создаётся следующей командой `$speckit-tasks`, не этим workflow.

### Source Code (repository root)

Планируемая структура; исходные файлы сейчас не создаются:

```text
pyproject.toml
uv.lock
src/sessions_manager/
├── __init__.py
├── __main__.py
├── cli.py
├── config.py
├── models.py
├── catalog.py
├── discovery.py
├── search.py
├── statistics.py
├── activity.py
├── cleanup.py
├── fsops.py
├── launch.py
├── warp.py
├── sources/
│   ├── base.py
│   ├── codex.py
│   ├── claude.py
│   ├── grok.py
│   ├── cursor.py
│   ├── sqlite_reader.py
│   └── cursor_wire.py
└── ui/
    ├── app.py
    └── screens.py
tests/
├── unit/
├── contract/
├── integration/
├── acceptance/
├── performance/
├── fixtures/
└── support/make_corpus.py
```

**Structure Decision**: CLI и TUI обращаются к общим функциям приложений и models;
adapters изолируют native schemas. Отдельные fsops/launch нужны из-за реальных границ
безопасности, не для построения framework. Tests support генерирует искусственные корпуса,
а приватные runtime data не располагаются под repository root.

## Design Decisions and Boundaries

```mermaid
flowchart LR
    UI["CLI / TUI"] --> Read["Discovery / Search / Stats"]
    Read --> Catalog["Private SQLite catalog"]
    Read --> Adapters["Versioned source readers"]
    Adapters --> Native["Native local histories"]
    UI --> Launch["Validated argv + cwd"]
    Launch --> CLI["Original CLI / Warp helper"]
    UI --> Cleanup["Confirmed cleanup coordinator"]
    Cleanup --> Vault["Private trash + journal"]
    Cleanup --> Native
```

- Discovery использует только configured roots и direct readers. Scan workers ограничены,
  один writer публикует согласованные session generations. UI не ждёт полный длинный scan,
  но всегда отличает cached/stale/partial от полного результата.
- Metadata-first даёт ранний обзор; content indexing идёт в том же управляемом refresh.
  Частичный индекс не считается выполнением полного поиска или SC-002.
- Каталог обновляется по source revisions/fingerprints; замена/усечение JSONL пересобирает
  соответствующую историю, append читает только новый подтверждённый хвост.
  Корень с ошибкой не вызывает массовое исчезновение ранее известных сессий.
- Refresh полностью обновляет все настроенные корни выбранных источников; project/date
  filters применяются только к выводу. Записи вне фильтра обновляются, невыбранные roots
  сохраняют прежние generation/as_of и не помечаются missing.
- Каждая строка обзора различает display_id и native_id. Визуальное сокращение допустимо;
  полные значения сохраняются в деталях/JSON и используются для selection/native resume.
- Search хранит casefolded chunks; FTS trigram даёт кандидатов, final literal check — истину.
  Short query и %/_ имеют ту же семантику; metadata/native text не исполняются.
- Usage ledger хранит уникальные facts и many-to-many memberships; snapshots и context
  occupancy отдельны. Перекрывающиеся истории не дают двойного суммирования.
- Read-only native SQLite учитывает WAL и не создаёт sidecars/repair. Paired Codex DB
  snapshots имеют проверку совместимости и as_of range; атомарность между ними не выдумывается.
- Resume использует exact native IDs, абсолютные executables и cwd. Установленный
  generic agent не используется как Cursor. Нестандартный read root не даёт resume
  capability без доказанной связи с native runtime.
- Исходный history_locator отделён от execution cwd. Перенос проекта требует проверки
  привязки к прежней истории для выбранного профиля; при unsupported/unverified binding
  CLI не запускается, а вместе доступны причина, другая папка/отмена и manual guide.
  Непроверенные инструкции не выдаются за работающие команды.
- Warp — documented Tab Config + one-shot helper, не UI typing и не invented URI command.
  Config не содержит session metadata; timeout не запускает второй процесс автоматически.
- Trash работает только с exact proven bundles, verified backups, same-device no-replace
  operations и durable journal. Unknown activity требует closed assertion, известный
  writer запрещает действие. Необусловленная защита от нарушившего эти условия native writer
  не обещается; такой риск не скрывается за stat check или manager lock.
- Cross-device cleanup и Codex paginated cleanup недоступны в первом compatibility profile.
  Статистика, просмотр и скрытие от этого не пропадают.

## Validation and Delivery Gates

Все behavioral изменения начинаются с ожидаемо падающего теста. Ниже группы будущих
проверок, не сгенерированный tasks.md и не отчёт о выполнении тестов приложения.

| Граница | Требования | Критерии | Проверки |
| ------- | ---------- | -------- | -------- |
| Sources / overview | FR-001–FR-005, FR-008–FR-009, FR-026 | SC-001, SC-002, SC-008 | Четыре native shapes, WAL/projections, corrupt/unknown/absent, stable IDs |
| Search / history | FR-004, FR-006–FR-007, FR-024–FR-025 | SC-002, SC-003, SC-007 | Casefold/literal/date bounds, pagination, inert text, aliases/forks |
| Resume / Warp | FR-009–FR-012, FR-025–FR-026 | SC-004 | Exact argv/cwd, missing context, TUI handoff, one-shot/timeout, synthetic Warp |
| Hide / cleanup | FR-013–FR-019, FR-025–FR-026 | SC-006 | No-op cancel, active block, copy/fsync/rename faults, retry/restore conflict, neighbors |
| Usage | FR-020–FR-024 | SC-005, SC-007 | Receipts vs snapshots, global fact union, categories/coverage, Cursor unknown |
| TDD / isolation | FR-027 | Все SC | Synthetic-only roots, no network scan, no source data/log/fixture leakage |

Последовательность будущей реализации: базовые модели/catalog и source contracts;
обзор четырёх источников; история/поиск; resume/терминал/Warp; manager hide и проверенная
cleanup; статистика. Общие файлы сериализуются в порядке US1→US2→US3→US4→US5 из tasks.md.
Сквозной benchmark проводится рано, до закрепления неработоспособной схемы индекса.

Release gates:
1. Каждый поддержанный native profile проходит positive/negative fixture suite.
2. Каждая включённая mutation проходит fault/race/recovery tests; иначе capability unavailable.
3. Synthetic Warp runtime проверяется отдельно от доставки URI; real native resume требует
   осознанной ручной проверки владельца и не запускается во время планирования.
4. SC-002 измеряется на согласованном корпусе/машине. Превышение блокирует выпуск;
   target не ослабляется, partial не маркируется complete.
5. Ruff и relevant pytest suites проходят; docs/CLI contracts обновлены; GitHub PR содержит
   validation evidence. Личных историй, catalogs/fixtures corpora и credentials в diff нет.

[quickstart.md](quickstart.md) задаёт команды и ожидаемые результаты после реализации.
Текущая верификация планирования — структура/ссылки/traceability и read-only research,
не запуск отсутствующего приложения.

## Risks

- Native schemas не являются стабильным общим API. Версия/shape drift даёт явную деградацию
  отдельных capabilities, не бесшумное чтение чужого формата.
- Проекции/истории могут быть неполными или удалены родным retention. Менеджер не обещает
  восстановить отсутствующий native conversation из одного индексного заголовка.
- Подстрочный поиск короткого запроса и cold 1 ГиБ indexing могут стать bottleneck.
  Benchmark gate обязателен; выбор Python не считается заранее доказанным по скорости.
- Source process может держать FD после rename. Условие закрытости, live evidence и
  fail-closed source profiles обязательны, а whole-DB rollback недопустим.
- Warp delivery асинхронна и зависит от установленной версии. Поддержка исследованного
  build — аргументированная совместимость; end-to-end доказывается отдельной проверкой.

## Complexity Tracking

Нарушений конституции и разрешений на её обход нет. Bounded Cursor wire reader,
операционный журнал и launch helper обоснованы конкретными native форматами и рисками
R6/R10/R11; это части одного приложения, не отдельные сервисы.
