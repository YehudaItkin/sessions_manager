# Quickstart / Validation Guide

**Feature**: [spec.md](spec.md)
**Branch**: `001-session-command-center`
**Interface**: [contracts/cli.md](contracts/cli.md)

Реализация доступна в checkout. Автоматические результаты, ограничения и непроведённые
ручные gates приведены в [validation.md](validation.md). Примеры с изменением источников
выполняются только на искусственном наборе.

## 1. Prerequisites и установка

macOS, Python >=3.12 с SQLite FTS5 trigram, uv; Warp только для opt-in transport проверки.
CLI исходных инструментов нужны для настоящего resume, не для чтения fixtures.
Работа из корня checkout; GitHub remote — YehudaItkin/sessions_manager.

Установка locked окружения:

```sh
uv sync --locked --group dev
uv run sessions --help
uv run sessions --version
uv run ruff check .
uv run ruff format --check .
```

Ожидание: зависимости берутся из lock, help/version не читают историю.
Установка пользователя из готового checkout: `uv tool install .`, затем `sessions`.
Для разработки используется `uv run sessions`, чтобы Warp helper ссылался на то же окружение.

## 2. TDD и обязательные проверки

Перед реализацией каждого поведения сначала выполнить конкретный новый тест и записать
ожидаемое падение, затем минимальную реализацию и passing результат.
В test environment сетевые обращения запрещены; native executables заменены fixture children.
Config fixture использует discovery_roots_mode=replace, не перезаписывает HOME.

```sh
uv run pytest tests/unit tests/contract -q
uv run pytest tests/integration -q
uv run pytest tests/acceptance -q
```

Ожидание:
- unit: IDs, casefold literal search, dates, metrics normalization, token union;
- contract: CLI JSON/exit codes, четыре native shapes и capability reasons;
- integration: реальные искусственные JSONL/SQLite/WAL/protobuf stores;
- acceptance: пять пользовательских историй, terminal handoff и cleanup fault recovery.
Содержимое личных сессий не копируется в tests/fixtures и не попадает в snapshots.

## 3. Изолированный пробный набор

Generator — test utility, не product subcommand. Создаёт только synthetic stores,
expected IDs/метрики, fake CLI bindings и config с отключёнными default roots.

```sh
case_root=$(mktemp -d /private/tmp/sessions-manager-check.XXXXXX)
uv run python -m tests.support.make_corpus --output "$case_root" --profile mixed --sessions 40 --history-bytes 10485760
uv run sessions --config "$case_root/fixture.toml" --data-dir "$case_root/manager" refresh
uv run sessions --config "$case_root/fixture.toml" --data-dir "$case_root/manager" --format json list --scope all
uv run sessions --config "$case_root/fixture.toml" --data-dir "$case_root/manager"
```

Ожидание: overview появляется без первоначального выбора provider; четыре источника,
устойчивые handles, известные даты, явные missing metrics/capabilities.
В строке раздельно видны display_id и native_id; сокращение длинных значений заметно,
show/JSON сохраняют полные значения, launch/selection не используют усечённый native ID.
Fixture включает not-recorded Cursor lifetime tokens, Codex cleanup unavailable и
контрольные Grok/Claude значения без повторного счёта snapshot views.
Ни один production root не читается; generated source neighbors и fixture project hashes известны.

## 4. Поиск, детали и статистика

```sh
uv run sessions --config "$case_root/fixture.toml" --data-dir "$case_root/manager" list --query "СЕСС" --source grok --source claude
uv run sessions --config "$case_root/fixture.toml" --data-dir "$case_root/manager" --format json stats --group-by source
uv run sessions --config "$case_root/fixture.toml" --data-dir "$case_root/manager" --format json stats --since 2026-10-01 --until 2026-11-02
```

Выбрать ID из списка и выполнить show/resume --dry-run.
Casefold на кириллице, literal %/_, односимвольный поиск, границы дат, stable selection,
длинная история и terminal control payload проверяются acceptance tests.

Дополнительный контроль refresh: в одном выбранном источнике сессии проектов A и B;
фильтр показывает только A. Изменить synthetic metadata обеих сессий и обновить обзор:
после сброса фильтра B должна быть доступна уже с обновлёнными данными. Отдельный
невыбранный источник сохраняет прежние records/as_of, не получает ложный missing.
Project/model/activity/date/query filters не ограничивают enumeration выбранных roots.

Ожидание: scoped lifetime usage, а не «потрачено за эти даты»; known 0 отличается от null,
coverage видна. Forked/shared usage не удваивает общий итог.
Unreadable/unknown source оставляет доступными остальные, exit=3, не ложный complete.

## 5. Открытие без реальных AI-сессий

```sh
uv run pytest tests/acceptance/test_resume.py -q
uv run pytest tests/acceptance/test_warp.py -q
```

Обычные tests используют fake transport и harmless child, проверяя exact argv/cwd,
suspend/restore, missing cwd и невозможность создать «новую вместо старой».
Для перенесённого проекта история остаётся по исходному history_locator, а новая папка
создаётся отдельно в fixture. Независимый fixture resolver должен подтвердить старую
identity/контекст либо профиль должен отказаться до запуска. Нельзя засчитать только
совпадение строки argv как доказательство загрузки прежнего разговора.
При unsupported/unverified binding одновременно видны причина, другая папка/отмена и
manual guide; non-TTY не ждёт ввода, JSON содержит data.manual_resume_guide.
Инструкция содержит только проверенные шаги/команду справки, не исполняется автоматически.

Отдельная opt-in runtime проверка с установленной Warp:

```sh
uv run pytest tests/acceptance/test_warp_runtime.py --run-warp -q
```

Она создаёт только manager-owned Tab Config и fixture child; child фиксирует synthetic
argv/cwd/ack в private case root, без запуска Codex/Claude/Cursor/Grok.
Ожидание: URI delivery не выдаётся за conversation loaded, ticket нельзя повторить.
Отдельно проверяются spaces, quotes, dollar signs и braces в project cwd.
Настоящее resume выполняется позднее только по осознанному выбору владельца.
Для каждого provider/profile отдельно фиксируются текущий терминал и Warp, а также
обычный/перенесённый проект: выбранный native ID и узнаваемый контекст контролируемой
одноразовой истории должны сохраниться. Непроверенная комбинация остаётся unavailable
с ручной инструкцией; вместо неё нельзя засчитать успешный запуск harmless child.

## 6. Скрытие, корзина и восстановление

Только на наборе из раздела 3:
1. Скопировать manager ID fixture Grok/Claude/Cursor из list.
2. Выполнить hide, refresh и unhide; native bytes не меняются.
3. Выполнить delete ID без --confirm: получить только preview.
4. Повторить точный набор с --confirm выданным token и --assert-closed для unknown:
   entry становится trashed, остальные native/project hashes прежние.
5. Выполнить trash restore TRASH_ID: preview и отдельное подтверждение; native identity
   и история возвращаются. Предварительно созданный target даёт conflict без overwrite.
6. Повторно удалить fixture; trash purge выдаёт новый irreversible preview.
   Отмена сохраняет bundle; подтверждение удаляет только этот trash payload.
7. После прерывания смотрите operation_id в `trash list`; команда
   `trash retry OPERATION_ID --assert-closed` повторяет сохранённую операцию.
8. Delete fixture Codex paginated даёт unavailable/native_cascade_unbounded без mutation.

```sh
uv run pytest tests/integration/test_cleanup_recovery.py -q
uv run pytest tests/acceptance/test_cleanup.py -q
```

Ожидание: crash/fault после каждой границы операции сохраняет recoverable copy;
retry не дублирует entry; active/writer/changed source/expired token/unsafe path блокируют
действие. Unsupported volume/no-replace/cross-device не превращается в unsafe fallback.
Ни native purge, ни remote delete не вызываются.

## 7. Performance gate

В отдельном приватном каталоге, на целевой машине владельца:

```sh
perf_root=$(mktemp -d /private/tmp/sessions-manager-perf.XXXXXX)
uv run python -m tests.support.make_corpus --output "$perf_root" --profile mixed --sessions 10000 --history-bytes 1000000000
uv run pytest tests/performance --corpus "$perf_root" -q -s
```

Native stores добавляют overhead: requested history bytes намеренно меньше 1 ГиБ.
Точный объём в `expected.json.native_bytes`; финальный корпус — 1 054 646 020 байт.
`expected.json` также содержит ID, provider counts и контрольные метрики.
Время генерации не входит в результат приложения. Измеряются cold refresh/search readiness,
новый процесс с warm catalog, первый содержательный TUI экран, paged history и literal
search (включая short query) на всей согласованной выборке.
Цели SC-002: cold <=10 с; warm overview/search/navigation <=2 с. Фиксируются OS/hardware,
cache condition, corpus seed, profile mix и completeness.
Partial search не считается выполнением полного запроса ради укладывания в срок.
При превышении gate выпуск не проходит; target нельзя молча ослабить.

## 8. Итог приёмки

SC-001–SC-008 сопоставлены планом с тестовыми границами. Требуются passing results,
per-source capabilities без ложных обещаний, отсутствие исходящих сетевых обращений при
просмотре и неизменность native history/project neighbors.
Перед публикацией проверяется git diff на отсутствие личных историй, private catalogs,
credentials и generated fixture corpora; коммитятся только код/документация и synthetic seeds.

## 9. Профили и оговорки первой версии

Матрица версий, config и клавиши TUI приведены в [README](../../README.md).
`f` включает направление сортировки, `v` меняет scope, `Space` задаёт batch.
TUI stats предлагает source/project/day; show включает usage и capabilities.
Произвольные explicit Grok/Cursor roots остаются view-only. Для Claude cleanup версия определяется через --version (или задаётся явно);
Grok/Cursor также определяют версию автоматически; явный executable_version остаётся override. Всегда нужен проверенный bundle; Codex cleanup недоступен.
Codex 0.166.0 history_mode=paginated допускает новый cwd после native gate; остальные
relocated-cwd профили пока отклоняются.
JSON foreground resume сохраняет один envelope в stdout, вывод child направляет в stderr.
Нативные разговоры автоматически ради приёмки не запускаются.

Клавиши после исправлений 2026-11-03: F5 — refresh, o — открыть исходный CLI,
r только внутри корзины — restore; d — Move to trash, t — показать корзину.

## 10. Воспроизводимая native Codex проверка

```sh
uv run python -m tests.support.verify_native_codex --executable /absolute/path/to/codex
```

Только opt-in для 0.166.0. Скрипт создаёт новый private offline CODEX_HOME в temp,
не читает credentials и не запускает личные сессии. Ожидаемый receipt: same_identity,
history_loaded_after_restart, archive_unarchive, neighbor_preserved, missing_original_cwd,
cli_resume_loaded_context=true; new_sessions_from_resume=0.
Warp `--run-warp` на установленной 0.2026.10.21 не прошёл; не считать его passing gate.

## 11. Фильтры и сортировка

В TUI откройте Filters / sort кнопкой или f, отметьте несколько источников (Space),
задайте project/model/activity/период и sort/direction, Apply. Заголовок таблицы также
сортирует кликом; повторный клик меняет направление. Настройки видны над таблицей и
переживают F5. Reset all/Escape в основном списке возвращает defaults, Escape в диалоге
отменяет редактирование. После обновления F5 заполнит новые Claude model metadata.

```sh
sessions list --source codex --source claude --model gpt --activity unknown --sort created --order desc
sessions list --sort project --order asc
sessions refresh --source claude --model sonnet --sort size --order desc
sessions stats --model sonnet --activity inactive --group-by project
```

Source choices — OR, разные фильтры/поиск — AND. Даты по last activity, включительно;
unknown исключается из периода, а при сортировке остаётся в конце в обоих направлениях.
Сортировка сохраняет выбранный ID; скрывшиеся после фильтрации записи снимаются с batch.
Сохранение настроек между отдельными запусками не добавлено.


## Convergence smoke — 2026-11-05

На synthetic fixture выполнить list --query по сообщению, отсутствующему в первом
preview: результат показывает контекст и роль, исходный preview в show не меняется.
Проверить сокращённый manager ID после смены страницы/фильтра; он выбирает ту же
единственную сессию. Во время cold TUI refresh видны ранние метаданные с partial.
В статистике переключить All/Visible/Hidden, закрыть и открыть: scope сохраняется,
фильтры/выбранные IDs/временные границы видны, trash не входит в выборку.
Cursor context fixture воспроизводится test_cursor_usage.py; ноль известен только
при записанном значении, lifetime input/output/total не оцениваются из context.

JSONL cache находится только в private manager catalog. Prefix SHA-256 проверяется
чтением старых байтов; JSON декодируется только для нового полного хвоста.
Замена/усечение/дрейф версии пересобирает checkpoint; purge удаляет его вместе
с cached history выбранной trashed-сессии. Это не обещание tail-only disk I/O.
Warp native runtime по-прежнему blocked; для запуска использовать Current terminal.


## Native Codex archive acceptance

Use an independently closed supported Codex home. In the TUI choose one Codex row and
Archive (a), review every descendant/flag, confirm closed status and the exact action.
The rows leave the active view; Archives (b) retains them. Select the parent and Unarchive
(u): original IDs/hidden state and previously archived descendants are preserved. A
partial result remains listed by operation ID and can be retried with r on its operation
row, or `sessions archive-retry OPERATION_ID --assert-closed`. Archive preserves disk data.

Reproduce the harmless native gate explicitly (no personal stores or credentials):

```sh
uv run pytest tests/acceptance/test_codex_archive_runtime.py -q -s \
  --codex-archive-executable /absolute/path/to/codex
```

It creates four native synthetic paginated histories with a closed loopback provider,
seeds only their fixture spawn edges while the native writer is stopped, then verifies
real native cascades and manager recovery across restart. No HOME substitution, direct
production native DB mutation, real provider call or personal session is involved.


## Phase 12 regression and statistics smoke

```sh
uv run pytest tests/integration/test_cleanup_recovery.py tests/integration/test_native_archive.py tests/integration/test_source_storage.py tests/contract/test_date_provenance.py tests/acceptance/test_native_archive.py -q
```

Use only the explicit synthetic config from section 3. Run JSON/human stats and stats
for one session/project: source_storage remains the whole selected source roots, separate
from known_session_bytes. Open statistics twice without refresh: observation/as_of stay
cached. Synthetic trash/restore/purge followed by refresh updates bytes; an unavailable
root keeps its dated observation with stale/incomplete coverage. These sizes are not
reclaimable space. Dates without timezone show ambiguous; UTC dates remain usable.

Catalog v1/v2/v3 upgrades to v4 on open, retaining IDs/hidden/history and operation journals.
Use the current binary afterward; older binaries refuse v4. Before any manual rollback,
retain the existing manager catalog and use a separately preserved compatible catalog;
never overwrite native shared stores. Unconsumed legacy archive previews require a fresh
preview; interrupted operations retain same-scope retry. Native Warp remains blocked by
the recorded access denial; no automatic retry or alternate UI/shell gate is authorized.


## Phase 13 synthetic recovery and boundary smoke

Use disposable fixture roots only. Put the same Claude native ID under two projects in
one root, then refresh: identical history/cwd/graph yields one manager row; differing
copies report identity_conflict without arbitrary details/search/usage. Reverse file
enumeration and refresh warm, then remove one copy and refresh: UID/hidden state remain.
Resume revalidates all copies; cleanup requires exactly one proven location and refuses
a duplicate introduced after preview before any source move.

Inject interruption after lifecycle ownership, staging intent/directory/manifest, and
after terminal item before owner release. Reopen the catalog. `sessions trash list` must
show the original operation ID even before a TrashEntry exists, with no claim of a ready
recoverable copy. Retry with `sessions trash retry OPERATION_ID --assert-closed`, or t →
Retry (x) → original targets/closed assertion → Confirm in TUI. Verify one entry, released
ownership, restored source bytes and unchanged neighbors; no new target selection.

For narrow Grok/Cursor roots, exercise workspace/session/dangling links and directory
substitution against an outside sentinel. No outside subtree is listed or counted;
coverage is partial/unknown. Explicit configured root aliases remain supported.
Config `sources=1`, `[sources]` or `enabled="false"` returns invalid_config/exit 2 before
runtime state. Valid `enabled=false` skips refresh without changing prior generation/as_of.
