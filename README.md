# Sessions Manager

Общий локальный CLI-центр для сохранённых сессий Codex, Claude Code, Grok и Cursor CLI.
Запуск `sessions` сразу открывает обзор: источник, содержание, проект, даты и доступные
действия. Есть поиск по истории, продолжение в исходном CLI, скрытие, восстановимая
корзина и статистика с явным покрытием данных.

Первая версия: **macOS, Python ≥3.12, SQLite FTS5/trigram**.
Статус приёмки и ограничения: [validation.md](specs/001-session-command-center/validation.md).

## Установка и запуск

Из checkout с установленным [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked --group dev
uv run sessions --help
uv run sessions
```

Установка команды в пользовательское окружение: `uv tool install .`, затем `sessions`.
AI CLI нужны для продолжения, но не для чтения сохранённых файлов.
Warp устанавливается отдельно и нужен только при выборе этого терминала.
Без параметров в терминале открывается TUI. При перенаправлении выполняется `list`,
без ожидания клавиатуры. Help/version не читают историю.
Первое обращение создаёт каталог; последующие показывают кеш с `as_of`.
Нажмите `F5` или выполните `refresh`, чтобы перечитать источники.

| Клавиша | Действие |
| --- | --- |
| `Enter` | Детали, полные ID, история по 100 событий и показатели |
| `/` | Буквальный поиск без учёта регистра |
| `f` | Источник, проект, даты, скрытые, порядок сортировки |
| `Esc` | Сброс фильтров / закрытие диалога |
| `F5` / `o` | Обновить / открыть выбранную сессию в исходном CLI |
| `r` в корзине | Восстановить выбранную запись (после подтверждения) |
| `Space` | Добавить строку в групповой выбор |
| `h` / `v` | Скрыть или вернуть / сменить область списка |
| `d` / `t` | Move to trash: перенос в корзину / открыть корзину |
| `s` | Статистика по источнику, проекту или дню |
| `q` | Выход |

## Команды

Глобальные параметры указываются **перед** подкомандой:

```sh
sessions list --source codex --source claude --query "ошибка" --sort recent
sessions list --project sessions_manager --since 2026-10-01 --scope all
sessions --format json list --limit 100 --offset 0
sessions show MANAGER_ID --offset 0 --limit 100
sessions resume MANAGER_ID --dry-run
sessions resume MANAGER_ID --terminal current
sessions resume MANAGER_ID --terminal warp
sessions hide MANAGER_ID
sessions unhide MANAGER_ID
sessions stats --session MANAGER_ID
sessions --format json stats --group-by source
sessions refresh --source claude
sessions sources list
sessions doctor
```

Замените `MANAGER_ID` значением из списка. Короткий manager ID допустим только при
единственном совпадении. Родной ID обозначен отдельно; JSON и детали сохраняют его полностью.
Поиск понимает подстроку, включая `%` и `_`, без regex или языка FTS.
Источники объединяются через OR, остальные фильтры — через AND.
Даты включительны в показанном локальном часовом поясе, неизвестные даты всегда в конце.
`refresh --source` перечитывает **все сессии всех включённых корней** выбранного источника;
проект/даты ограничивают только вывод.

JSON — один объект со `schema_version=1`, `data`, `sources`, `completeness`, `warnings`, `error`.
Частичное перечисление или поиск возвращает код 3; unavailable — 4.
При JSON resume вывод дочернего CLI идёт в stderr, результат — в stdout.
Все параметры и коды: [CLI contract](specs/001-session-command-center/contracts/cli.md).

## Источники и конфигурация

Стандартные корни: `CODEX_HOME` или `~/.codex`, `CLAUDE_CONFIG_DIR` или `~/.claude`,
`~/.grok`, `~/.cursor`. Чтение прямое, без native list/export/SDK.
Для Cursor выбирается `cursor-agent`; неоднозначный `agent` не используется.

| Профиль | Чтение и статистика | Продолжение и уборка |
| --- | --- | --- |
| Codex 0.166 paginated / известный JSONL | `state_5`, обычные/realtime items проекции и rollout; response receipts и отдельные legacy snapshots | По ID в проверенном контексте; cleanup отключён (`native_cascade_unbounded`) |
| Claude Code 2.1.299; совместимые JSONL 2.1.x до 2.1.299 | Сообщения, ветви, tool events; последний корректный usage по `message.id` | По ID; cleanup для 2.1.299 только transcript и известных companions, включая завершённые workflows |
| Grok Build 1.0.70 | `summary.json`, ACP updates или известный raw chat fallback, `usage.json` | По ID; только доказанный локальный bundle, без remote delete |
| Cursor CLI 2026.10.22-27dcf5f | schemaVersion 1, ограниченная protobuf-проекция достижимого графа | По ID; только проверенный целый per-chat bundle |

Неизвестные узлы/форматы дают partial/unavailable. Lifetime tokens Cursor остаются `null`.
Недоказанное заполнение контекстного окна не считается расходом. Перекрывающиеся Grok
snapshots разных сессий не суммируются без доказательства независимости.
Сбросы legacy Codex counters и неизвестное перекрытие с receipts обозначаются как partial.
Фильтр дат в статистике выбирает сессии по последней активности, затем считает **всю историю**.
У Grok читается native envelope `usage.json.session`, старый плоский формат также
поддержан; turns/modelUsage не суммируются повторно. Если usage.json отсутствует,
показатель остаётся unknown/not_recorded.
Поле Project — исходный cwd; History location — место сохранения разговора.
Например, проект в PycharmProjects может иметь историю под ~/.grok.
Скрытые включены по умолчанию, корзина исключена. Общие факты учитываются один раз;
для пересекающихся групп есть `shared_usage`. Временной диапазон не означает часы работы.
Последняя запись в файле не означает работающий процесс.

```sh
sessions sources add claude --path /absolute/path/to/claude-home --namespace work
```

Config по умолчанию: `~/Library/Application Support/sessions-manager/config.toml`.
Другие пути: `--config PATH --data-dir PATH`. Пример (подставьте реальные пути и версию):

```toml
discovery_roots_mode = "extend"

[[sources]]
provider = "claude"
path = "/absolute/path/to/claude-home"
namespace = "work"
enabled = true
executable = "/absolute/path/to/claude"
resume_context = "native"
executable_version = "2.1.299"
```

`replace` полностью отключает стандартные корни для изолированного набора.
Namespace различает профили одного инструмента. Копии одного namespace дедуплицируются;
несогласованные копии блокируют неоднозначные действия и историю.
Добавленный путь изначально view-only. Для Codex/Claude допустим проверенный native-home
context; произвольные Grok/Cursor homes остаются view-only даже при `resume_context="native"`.
Для Claude версия определяется ограниченным вызовом `claude --version`, если не задана
явно. Поддержана версия CLI 2.1.299 и совместимые записи JSONL 2.1.x до 2.1.299; каждая
запись проверяется по identity и форме сообщения. Для Grok/Cursor executable_version
по-прежнему задаётся явно. Неизвестная версия или структура не включает удаление.
При смене executable версия проверяется заново; restore проверяет её и в новом процессе.

При пропавшем проекте доступны выбор существующей папки, отмена и ручная инструкция.
Автоматический resume в перенесённом cwd пока недоступен для всех профилей до отдельной
native-проверки привязки. История не переносится и не заменяется новым разговором.
Warp delivery означает передачу запроса, а не подтверждение загрузки разговора.

## Корзина и восстановление

`hide` меняет только каталог менеджера. **Delete / Move to trash** переносит историю
в восстановимую корзину, **Trash** открывает корзину, **Restore** возвращает сессию.
**Purge** удаляет её окончательно с отдельным подтверждением.
`delete` сначала показывает точный план и token:

```sh
sessions delete MANAGER_ID
sessions delete MANAGER_ID --confirm TOKEN --assert-closed
sessions trash list
sessions trash restore TRASH_ID
sessions trash restore TRASH_ID --confirm RESTORE_TOKEN
sessions trash purge TRASH_ID
sessions trash purge TRASH_ID --confirm PURGE_TOKEN
sessions trash retry OPERATION_ID --assert-closed
```

Token относится к показанному набору и истекает через 5 минут. Purge требует собственного
подтверждения и необратим. `--assert-closed` подтверждает неизвестную активность, но не
обходит известный живой процесс, открытый файл или SQLite writer.
Перед изменением создаётся проверенная копия с hash/fsync и durable journal.
Перемещение использует macOS no-replace rename на том же устройстве;
cross-device/unsafe layout отклоняются. Restore не перезаписывает существующий target.
Проекты и соседние сессии не удаляются. После сбоя `trash list` показывает
`recovery_required` и operation ID; `trash retry` продолжает прежний набор.
Не перемещайте вручную файлы незавершённой операции.
Автоматического удаления старых историй или содержимого корзины нет.

Просмотр, поиск и статистика работают offline, не обращаются к AI и не читают credentials.
Каталог, поисковый кеш, launch manifests и корзина содержат локальные данные сессий:
директории защищены режимом 0700, файлы — 0600. Не используйте общий data-dir.
Логи/ошибки не содержат разговоров. Нативные SQLite открываются read-only с WAL,
без repair, checkpoint, extensions или создания отсутствующих sidecars.
Своя БД имеет application ID и schema v1; чужая/более новая схема отклоняется.
Это первый выпущенный формат, миграция старых выпущенных каталогов не требуется.

## Разработка и приёмка

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest tests -q
uv build
```

Тесты используют искусственные stores, блокируют сеть и не подменяют HOME.
Performance требует явного `--corpus`; настоящий Warp — `--run-warp`.
Synthetic demo, 10 000 сессий, fault recovery и ручные native-проверки:
[quickstart](specs/001-session-command-center/quickstart.md).
Реальный native resume и Warp runtime ещё требуют ручной проверки владельцем.
Решения и scope: [spec](specs/001-session-command-center/spec.md),
[plan](specs/001-session-command-center/plan.md), [tasks](specs/001-session-command-center/tasks.md).
