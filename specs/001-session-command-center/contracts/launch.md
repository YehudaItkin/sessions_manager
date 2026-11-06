# Launch Contract: current terminal и Warp

**Version**: 1
**Requirements**: FR-010–FR-012, FR-025–FR-027.
Состояния — [data-model.md](../data-model.md#6-запуск).

## 1. Общий LaunchPlan

Валидированный LaunchPlan содержит session identity, source fingerprint, абсолютный
executable, отдельный список argv, исходный history_locator, существующий cwd запуска,
target и только доказанные native-home context overrides. Нет prompt, permission bypass,
fork/new-session или last/latest. history_locator сохраняет выбранные namespace, native ID,
расположение истории и исходную workspace-привязку независимо от выбранного cwd.

Ниже приведены обычные argv для подтверждённого native context. Подстановка нового cwd
сама по себе не доказывает, что источник найдёт прежнюю историю. Для каждого профиля
build_resume проверяет сочетание history_locator/native ID/нового cwd и использует только
доказанную форму native resume. Неподтверждённая комбинация не становится LaunchRequest.

| Provider | Argument vector после executable |
| -------- | -------------------------------- |
| codex | resume, native_id, -C, cwd |
| claude | --resume, native_id |
| cursor | --workspace, cwd, --resume, native_id |
| grok | --cwd, cwd, --resume, native_id |

Process cwd задаётся явно для всех четырёх. Для Cursor не использовать generic agent.
Нестандартный history root не считается автоматически native resumable context.
В первой версии произвольные explicit Grok/Cursor roots остаются view-only; Codex/Claude
могут использовать только проверенный allowlisted native-home override.
Автоматическое продолжение в другом cwd проверено для Codex 0.166.0
history_mode=paginated: cold native CLI загрузил прежний ID и искусственную историю
после исчезновения исходной папки, без fork/new session. Rollout для этого профиля
не обязателен. Другие профили отклоняют новый cwd до своего gate; исходный history
locator остаётся неизменным.
Выбор пропавшего cwd: существующий альтернативный каталог либо отмена; нельзя mkdir или
молча взять cwd менеджера. Утрата native session не приводит к замене новой.

Если продолжение выбранной сессии в новой папке не поддержано или не подтверждено:
- Не запускать CLI, не менять history_locator/session identity и не переносить native data.
- Одновременно показать причину, другую папку/отмену и ManualResumeGuide.
- Guide содержит provider, полный native ID при наличии, исходное расположение истории,
  исходную/выбранную папки, ограничение привязки и шаги ручного запуска по проверенным
  возможностям профиля. При отсутствии проверенного рецепта для новой папки указать это
  явно и дать известную команду справки; не выдумывать рабочие native флаги.
- Подтверждённая shell-команда в guide строится только из проверенного argv с quoting
  для явно указанной shell. Содержимое истории или сохранённые tool commands не исполняются.
- Guide доступен в пользовательском выводе, но не в diagnostics; он не исполняется
  автоматически. Non-TTY не ждёт ответа; JSON использует data.manual_resume_guide.

Unsupported binding даёт reason=resume_cwd_unsupported, ещё не подтверждённая привязка —
resume_binding_unverified; оба завершаются exit 4 без ticket/child. Ошибка уже начатого
подтверждённого запуска по-прежнему отличается от отказа до запуска.

Перед реальным handoff заново проверяются identity, history_locator, подтверждённая
привязка нового cwd, executable/source profile и cwd.
Native CLI получает обычное окружение своего терминала и отвечает за аутентификацию;
его credentials не читаются и не сохраняются менеджером.

## 2. Current terminal

Textual останавливает scan workers/короткие native read connections перед handoff,
использует App.suspend() и foreground subprocess с inherited stdin/stdout/stderr,
argv list и shell=False. Никакого capture transcript в logs.
При --format json вне TUI stdout child направляется в stderr; manager stdout содержит один envelope.
После выхода/ошибки/Ctrl-C терминал и UI восстанавливаются, source refresh выполняется
без потери выбранного ID. В non-TUI режиме тот же service запускает child напрямую.
Отказ exec/ненулевой exit объясняется без заявления, что разговор успешно загружен.

## 3. Warp transport

Документированный путь: manager-owned TOML в `~/.warp/tab_configs/`,
URI `warp://tab_config/sessions_manager_<opaque_name>` через argv вызов /usr/bin/open.
Не использовать new_tab?command=, UI typing, AppleScript или Warp Agent Mode.

Config: фиксированные name/title, один terminal pane, directory=/, shell=zsh и одна
startup command. zsh проверяется до создания config. tomli-w сериализует TOML.
Команда состоит только из доверенного абсолютного interpreter/manager launcher,
global --data-dir и внутреннего _launch с одноразовым ticket.
POSIX quoting применяется лишь к этим доверенным manager paths и ограниченному ASCII token.
Исходные session ID, cwd, title, transcript и tool commands не включаются в config/URI.
Шаблонные delimiters Warp в launcher/data-dir отклоняются; project path с braces
безопасно передаётся внутри private manifest, не через Warp template.

Manifest 0600 содержит LaunchPlan; directory 0700. Ticket >=128 случайных бит,
120 секунд TTL, digest/owner/state сохраняются в manager catalog.
Helper проверяет uid, owner/mode, expiry, single-use claim и заново source/cwd/executable;
затем создаёт foreground child напрямую, без eval/shell command reconstruction.
Root-independent --data-dir из config ведёт к тому же private registry и проверяется.

Новая config создаётся O_EXCL с уникальным именем; пользовательские configs/default
не перезаписываются. После open config не удаляется немедленно: Warp читает асинхронно.
Удаление manager-owned launcher/config/manifest разрешено после claim/expiry и завершения
его использования; это housekeeping launch artifacts, не session trash retention.

Статусы:
- requested — подготовлено;
- delivered — open принял URI, native CLI ещё не подтверждён;
- claimed — helper принял ticket;
- handoff_attempted — начат запуск правильного child;
- exec_failed / child_exited / expired / delivery_failed — явные результаты.

Delivered/claimed/handoff_attempted не равны подтверждённой conversation_loaded.
Ответ delivered включает human message: при отсутствии CLI выбрать Current terminal;
TUI показывает это сообщение вместо одного технического статуса.
При таймауте показывается pending/expired и возможность явного повтора;
таймаут не запускает второй CLI автоматически.

## 4. Verification

- CliRunner проверяет dry-run plans всех четырёх профилей с exact argv/cwd.
- Textual Pilot + synthetic child проверяет suspend/return/interrupt.
- Fake transport проверяет URI, owner-only files, expired/replayed/tampered ticket.
- Synthetic Warp runtime test с установленной Warp открывает безвредный fixture executable,
  записывающий только fixture argv/cwd/ack. Только opt-in, без реального AI provider.
- Cases: spaces, кириллица, кавычки, dollar signs, literal braces в cwd, metadata injection,
  неверный agent alias, missing CLI/cwd/Warp и failed exec.
- Для перенесённого проекта fixture resolver независимо проверяет выбор прежней истории,
  не только записанный argv. Unsupported/unverified binding не запускает child и даёт
  сразу оба варианта помощи: другую папку/отмену и manual guide без непроверенной команды.
- Настоящее native resume требует отдельной осознанной ручной проверки пользователем;
  подтверждение relocated-workspace binding фиксируется отдельно по provider/profile и
  способу запуска. До такой проверки неподтверждённая комбинация не рекламируется как
  поддержанная. Во время планирования реальные native сессии не запускались.

Источники транспорта: [Warp Tab Config](https://docs.warp.dev/terminal/windows/tab-configs/),
[Warp URI](https://docs.warp.dev/terminal/more-features/uri-scheme),
[Textual suspend](https://textual.textualize.io/api/app/#textual.app.App.suspend).

## Native gate update — 2026-11-03

`tests.support.verify_native_codex --executable /absolute/codex` создаёт новый private
CODEX_HOME с offline provider на закрытом loopback port 9. HOME не подменяется, credentials
не копируются. Native app-server создаёт две искусственные сессии и историю, проверяет
restart, archive/unarchive и соседа; затем PTY запускает настоящий
`codex --no-daemon resume ID -C moved --no-alt-screen` после rename исходной папки.
Проверяются записанный marker в UI, прежний ID/cwd в native DB, отсутствие новой сессии.
Эти flags изолируют только тест; production argv остаётся обычным exact resume.

Harmless Warp runtime был запущен на установленной 0.2026.10.21.08.25.02: URI принят,
но ticket остался requested и fixture child не стартовал за 20 секунд. Gate FAIL,
conversation_loaded не заявляется. Computer Use запретил доступ к Warp; обход UI запрета
не применялся. Native startup state не установлен. Current terminal — рабочая альтернатива.


## Convergence safety amendment — 2026-11-05

The Warp launcher directory must be owned by the current user and neither group
nor world writable. Every existing ancestor must be a trusted directory without
symlinks or foreign write access; root-owned sticky ancestors protect owned
children and are permitted. Validation precedes creating directories, tickets,
configs or opener handoff. Existing paths are never chmodded automatically.
Missing/non-executable native binaries cannot advertise resume supported.
Foreground child return includes the exit code and an actionable exit/interruption
message, and TUI restores the terminal and original stable selection.
Native Warp runtime gate T113/T130 remains blocked by Computer Use access policy.


## Phase 10 alias amendment — 2026-11-05

Known copies of one namespace/native ID require fresh full-history digest agreement in
one refresh cycle, including multiple physical locators within the same configured root.
While peers are pending/failed/cancelled, available history is partial
and resume/cleanup are blocked with identity_binding_unverified. Actual differences in
content or parent/turn membership produce identity_conflict. Verified empty enumeration
may remove an absent peer; a failed root never proves absence. Unrelated IDs are isolated.
Matching copies can resume but cleanup remains multiple_locations_unverified.

LaunchRequest.alias_bindings records every agreed root/locator/fingerprint. Both request
construction and handoff consult the current private catalog guard read-only, preventing
single-root rediscovery from dropping an existing alias guard. Handoff rechecks every
copy; changed evidence refuses exec. Warp uses the same request validation, with no
change to its externally blocked runtime gate.
Bindings must cover the exact current set of (root_id, locator), not just distinct roots.
Rediscovery verifies every copy and its fingerprint; a newly appeared copy blocks handoff.
For matching copies in one root, resume uses the verified request's selected locator.


## Phase 14 dialog and native acceptance — 2026-11-06

Open captures the selected stable UID plus root/locator/fingerprint/cwd observation and
shows its IDs/source/history location. Every terminal/cwd callback and manual-guide retry
uses that target, regardless of current table position/filter/order. A changed/missing
observation refuses with source_changed; the neighbor never replaces it. The final native
request still performs all existing catalog/source/executable/cwd revalidation.

Explicit native current-terminal gates for Claude/Grok/Cursor are separate from the
harmless Warp gate and the supported Codex 0.166.0 gate. Native output/exit or matching
argv alone is not conversation_loaded. The opt-in harness requires generated marker,
same ID, observed cwd, no new sessions and preserved neighbor. Its native child has an
isolated HOME/default roots, minimal environment, OS-denied network/keychain/personal
stores and writes confined to disposable files. Parent HOME is unchanged. Failure to
load under these boundaries remains unverified; the harness never weakens containment
or falls back to a real store. Warp's existing access denial remains in force.
