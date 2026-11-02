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
Автоматическое продолжение в другом cwd пока отклоняется для всех четырёх профилей,
до отдельного native gate; исходный history locator остаётся неизменным.
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
