# CLI Contract: sessions

**Version**: 1
**Scope**: FR-001–FR-027 из [spec.md](../spec.md).
Форматы данных — [data model](../data-model.md), native sources — [sources.md](sources.md).

## Запуск и глобальные параметры

`sessions` без подкоманды открывает Textual overview, только если stdin/stdout — TTY.
При перенаправлении выводит обычный list и завершается; не ждёт клавиатуру.
`sessions --format json` без подкоманды эквивалентен list в JSON.

Глобальные параметры: `--config PATH`, `--data-dir PATH`, `--format table|json`,
`--help`, `--version`. Config содержит только явные source roots/executable bindings
и настройки менеджера, не credentials. Небезопасный data-dir вызывает отказ.
CLI help/version не сканируют пользовательскую историю.

## Команды

| Команда | Результат |
| ------- | --------- |
| sessions | Интерактивный общий обзор или list для non-TTY |
| sessions list | Отфильтрованный список и здоровье/полнота источников |
| sessions show ID | Метаданные, доступная история и capability reasons |
| sessions resume ID | Точный native conversation, terminal=current по умолчанию |
| sessions hide ID... | Persistent manager-only скрытие |
| sessions unhide ID... | Возврат из скрытых без изменения native source |
| sessions delete ID... | Только preview удаления, если нет valid --confirm |
| sessions trash list | Восстанавливаемые и recovery_required записи |
| sessions trash restore TRASH_ID... | Preview восстановления, затем подтверждённая операция |
| sessions trash purge TRASH_ID... | Отдельный preview необратимой очистки |
| sessions trash retry OPERATION_ID | Продолжение точного сохранённого набора после прерывания |
| sessions stats | Per-session/сводные известные значения и coverage |
| sessions refresh | Обнаружение/обновление с прогрессом и явным состоянием завершения |
| sessions sources list | Корни, профили, версии, здоровье и возможности |
| sessions sources add PROVIDER --path PATH | Добавление явно выбранного локального корня |
| sessions doctor | Безопасная диагностика data-dir, SQLite/форматов и executable bindings |

`sources add` принимает `--namespace NAME` для отдельного профиля; default — default
этого provider. История в нестандартном месте может оставаться view-only.
Не требуется первоначальная ручная настройка стандартных корней.
Config может задать discovery_roots_mode=replace для изолированного тестового набора;
в таком режиме native defaults вообще не читаются.

## Выборка и ID

Для list/stats/refresh доступны `--source codex|claude|cursor|grok` (повторяемый),
`--project TEXT`, `--model TEXT`, `--activity active|inactive|unknown`,
`--since ISO-DATE-OR-TIME`, `--until ISO-DATE-OR-TIME`.
List/refresh дополнительно: `--query TEXT`, `--scope visible|hidden|all`,
`--sort updated|created|source|project|title|id|manager-id|model|activity|size`,
`--order asc|desc`. Совместимые aliases recent/oldest сохраняют прежний порядок дат.
List также поддерживает `--limit N`, `--offset N`; сортировка до pagination.
Без order даты/size идут desc, текст asc; unknown last в обоих направлениях, ties по
session_uid asc. Title использует title либо preview; ID различает native id и manager-id.
Модель/проект — Unicode casefold substring. Model — последнее записанное значение,
activity — сохранённое наблюдение, включая unknown. Новые параметры валидируются до runtime.
Stats использует те же query/scope параметры при явной передаче; без них scope=all
(включая скрытые, без корзины). List default scope=visible.
`stats --session ID` ограничивает одной сессией;
`--group-by source|project|day` выбирает разбиение по последней активности.

У refresh параметр --source выбирает обновляемые источники: сканируются все настроенные
включённые корни каждого выбранного источника и все его сессии. Без --source обновляются
все включённые источники. --project/--model/--activity/--since/--until/--query ограничивают только показанную после
обновления выборку, не enumeration или reconciliation. То же правило действует для F5 в TUI.
Сессии вне фильтра выбранного источника обновляются; невыбранные корни сохраняют прежние
сведения/as_of и не помечаются missing. Признак полного scan относится к корню целиком,
а не к отфильтрованной странице вывода.

Поиск — буквальная Unicode casefold подстрока в полях и содержимом отдельного события,
не regex/FTS language. Фильтры соединяются AND; повторённые source — OR между источниками.
Период включителен с обоих концов. Одна календарная дата задаёт начало/конец локального
дня соответственно; timestamp без timezone трактуется в явно показанном локальном поясе.
Неоднозначный DST input требует offset, не угадывается.
Неизвестные/неоднозначные native даты не входят в фильтр периода.
Неизвестные даты всегда в конце, tie-break — session_uid.
List default limit=50, offset=0; total и способ следующей страницы видны.

ID — устойчивый manager handle. Укороченный ID допускается только при единственном
совпадении; неоднозначность/исчезновение — ошибка до действия. В каждой строке явно
обозначены ID менеджера (display_id) и родной ID (native_id); при отсутствии родного ID
показано «неизвестно». Длинные значения могут визуально сокращаться с многоточием;
show и JSON содержат полные значения. Сокращение не меняет identity/selection/native argv.
Краткий manager handle остаётся однозначным: при коллизии увеличить префикс или показать
полное значение. Визуально усечённый native ID не становится допустимым manager selector.
Native ID не принимается за универсальный номер строки или сокращённый manager selector.
`show --offset N --limit N` листает нормализованные события, по умолчанию 100.
Неподдержанная история не выдаётся за разговор из нуля сообщений.

## Продолжение

`resume ID --terminal current|warp [--cwd EXISTING_DIR] [--dry-run]`.

Отсутствующий cwd вызывает выбор в TTY, а в non-TTY требует явный --cwd.
Dry-run выводит валидированный LaunchPlan без запуска и без credentials.
Открытие не добавляет prompt, не выбирает latest/last и не включает bypass permissions.
Успех доставки в Warp называется delivery/handoff, не гарантией загрузки разговора.

history_locator исходной истории и cwd запуска различаются. Новый cwd не меняет выбранную
сессию; источник должен подтвердить, что конкретная форма resume найдёт прежнюю историю.
При unsupported/unverified binding автоматический запуск не выполняется (exit 4), а
вместе показываются причина, выбор другой папки/отмена и инструкция ручного запуска.
В non-TTY инструкция и варианты доступны в результате без ожидания ввода; другую папку
можно передать повторным resume с --cwd. Для JSON инструкции находятся в
data.manual_resume_guide, а не в диагностических логах. Непроверенные native флаги или
рецепты не генерируются; детали и правила безопасного вывода — в launch contract.

## Подтверждения уборки

Первая команда delete/restore/purge возвращает OperationPlan: action, точные ID, sources,
известный объём/unknown, эффект, ограничения активности, expiry и confirmation token.
Без token не выполняется source mutation даже в non-TTY.

Повтор той же команды с `--confirm TOKEN` применяет только этот план.
Для unknown activity у delete дополнительно нужен `--assert-closed`:
пользователь утверждает, что выбранные сессии закрыты и не будут открываться во время операции.
Known active нельзя обойти этим флагом. Generic --force/--yes не предусмотрен.
В TUI тот же план показывается в modal; default focus — отмена.
Purge требует отдельного предупреждения о необратимости и нового confirmation token.
План истекает через 5 минут и инвалидируется при изменении состава/источника.
Подробные состояния и ошибки — [cleanup.md](cleanup.md).

## Интерактивный обзор

Первый экран: ID менеджера (display_id), родной ID (native_id), provider, title/preview,
project, last activity, current activity,
capabilities; отдельно progress, stale/partial source status, hidden/trash counts.
Поиск и фильтры доступны без выхода. Enter — детали; / — поиск; o — open/resume;
F5 — refresh; r внутри корзины — restore; f — filters/sort; Esc — reset; v — scope; Space — batch selection;
h — hide/unhide; d — Move to trash (preview delete); s — statistics (source/project/day); t — trash; q — выход.
Выбор привязан к ID, не позиции строки при пересортировке. Видимая кнопка Filters / sort
и сводка показывают текущую выборку; диалог содержит подписанные поля, multi-source
SelectionList, отдельные sort/direction, Apply/Reset filters/Cancel. Пустые sources и
неверные даты сохраняют редактируемый диалог, не меняя текущую выборку. Заголовки всех
содержательных столбцов сортируются кликом (Actions исключён); повторный клик меняет
направление. Batch сохраняется при sort и ограничивается видимыми IDs после filter/search.
Escape/Reset all в основном списке очищает query/filter/sort; Escape в диалоге отменяет
его. Настройки действуют в текущем процессе и переживают refresh.
История выводится literal text без Rich markup/ANSI/OSC исполнения.
Диалог цели запуска предлагает current и Warp явно. Выход из native CLI возвращает
overview и обновляет соответствующий источник.

## JSON и ошибки

Один объект UTF-8 JSON в stdout; progress/diagnostics — stderr без transcript/секретов.
У foreground resume пользовательский вывод child направляется в stderr, чтобы stdout
сохранял ровно один JSON envelope. Он не перехватывается в журнал менеджера.
Version 1 envelope содержит:
- schema_version=1, kind и data;
- sources: health, capabilities/reasons и scan state;
- completeness: enumeration/history/search/usage + as_of;
- warnings и error: только устойчивые codes и безопасные пояснения.

Фиксированные data payloads:

| kind | Основные поля data |
| ---- | ------------------ |
| list | items (sessions), total, limit, offset |
| show | session, events, next_offset, usage (per-session lifetime summary) |
| stats | scope, metrics, groups, coverage, accounting_mode |
| operation_plan | plan_id, action, targets, known_bytes, bytes_complete, confirmation_token, expires_at |
| operation_result | operation_id, items (target_id, state, trash_id, error, recovery_options) |
| trash_list | items (trash_id, session_id, state, available_actions) |
| refresh | items (выбранные sessions), scans (receipts всех обновлённых roots), complete, state |
| sources / doctor | items; source-specific details без секретов |

Пример метрики: `{"value": null, "reason": "not_recorded", "known_sessions": 0,
"selected_sessions": 4, "complete": false}`.
Известный ноль — value=0; отсутствие lifetime tokens Cursor не превращается в 0.
В статистике указан scope=selected_session_lifetimes, union accounting и coverage;
shared_usage видна отдельно, общий итог не складывается из перекрывающихся session totals.

| Exit code | Значение |
| --------- | -------- |
| 0 | Запрошенное действие/preview завершено |
| 1 | Неожиданная внутренняя ошибка с безопасным сообщением |
| 2 | Неверные аргументы/ID/неоднозначный ввод |
| 3 | Частичный результат, отказ части источников или части batch |
| 4 | Возможность недоступна для выбранного источника/формата |
| 5 | Active/stale/conflict/unsafe layout |
| 6 | I/O, права или нехватка места; recovery state указан |
| 7 | Нужны confirmation/closed assertion или истёк token |
| 8 | Ошибка запуска исходного CLI или доставки Warp |
| 130 | Отмена пользователем / Ctrl-C |

Cancel до source change не меняет данные. Cancel после source change оставляет durable
recovery state. GUI/CLI используют одинаковые service results; UI не скрывает частичный успех.

## Human error presentation amendment — 2026-11-03

Human CLI/TUI render stable error/reason codes as explanations with recovery actions
(refresh, original cwd, configured executable, close native session, retained backup,
Hide, or Current terminal). Unknown codes have a safe generic explanation plus code.
Manual resume guidance retains native ID, history location and original/requested cwd,
with only the already verified help argv. Display translation does not alter serialized
JSON envelopes, confirmation plans/tokens, journal payloads or machine-readable codes.


## Convergence interface amendment — 2026-11-05

List/refresh JSON keeps full session IDs and adds per-result `handles` and `matches`
maps keyed by session_uid. Handles are computed against the entire selectable
catalog before filtering/pagination. A match contains bounded sanitized original
text, field/role and, for history, logical event_uid/ordinal. Native title/preview
is unchanged. Human results show the context and available actions; missing
title/preview is explicit unknown. Terminal escapes/markup remain inert.

Statistics adds `selection` (actual source/project/model/activity/date/query/scope
and explicit session IDs if selected) and `activity_range` (known UTC started_at/
last_activity_at plus completeness). Period filters still select session lifetimes.
TUI statistics has its own All/Visible/Hidden control, initially All; the chosen
value persists on reopening. Trash stays excluded. Context occupancy is displayed
separately in human output and `context_metrics`; it is never lifetime usage.

During refresh, early metadata is visible while history/search/usage remain partial
with scan_pending. Completed roots publish independently, including generation
reader times and source revision ranges. Error/unfinished roots do not mark
unseen cached sessions missing and never claim complete search.


## Native Codex archive (FR-028)

`archive MANAGER_ID [--confirm TOKEN --assert-closed]`, `unarchive MANAGER_ID` with
the same confirmation options, `archives`, and `archive-retry OPERATION_ID --assert-closed`.
One selected root session per plan; preview enumerates all affected descendants. JSON
kinds native_archive_plan/native_archive_result/native_archives extend envelope v1.
Plans contain members with stable session_id/native_id and before_archived/desired_archived/
archived flags, expiry and a separate token. Results report operation_id, action, state,
per-member flags, error and recovery_options. Complete returns 0; interrupted/partial or
failed_no_change commit/retry returns 3; precondition/confirmation errors retain existing
4/5/6/7 categories. Archive listing is cached and includes operation recovery history.
Default list/refresh/stats exclude native archived records independently of manager hide.
`show ID` can still inspect a cached archive; resume requires Unarchive and no pending
operation. CLI archive startup/reindex scans Codex roots only. Other sources are untouched.


## Phase 12 additive statistics/date presentation — 2026-11-06

stats JSON adds source_storage independently of metrics. Fields: scope=
whole_catalogued_history_roots, value (known unique logical bytes or null), complete,
cached, as_of, selected_roots/known_roots, deduplicated_files/conflicting_files, reason,
per-root provider/path/value/as_of/complete/stale/reason and explanatory notes. Device/inode
facts remain private. Source filters choose whole catalogued roots; session/project/date
filters do not divide shared bytes. For a single-session detail, source size refers to
its whole source. Unknown is not zero; all-conflicted evidence is null. Physical allocated
blocks/compression/freeable space are not claimed. Human stats label Source storage,
whole history roots and not reclaimable space; TUI statistics exposes the same fields.
Stats opening uses cached observations without rescanning native files.

Session JSON adds per-field extra.date_provenance confidence/reason and
ambiguous_native_dates. Human list/show/TUI explain ambiguous (timezone not recorded),
while absent/invalid dates remain unknown. Aware dates retain local-zone display and
participate in period filters even alongside naive dates; ranges show incomplete.

Opening Codex Archives handles service/list failures with a content-free explanation
and return to overview; an invalid journal is preserved and never reported as an empty
archive. cleanup_operation_pending blocks Open/new cleanup until same-operation recovery.
lifecycle_refresh_stale marks late/overlapping scan results partial; no cached state is
silently replaced. Machine codes and envelope version 1 remain stable/additive.
