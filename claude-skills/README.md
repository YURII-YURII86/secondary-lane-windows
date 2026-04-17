# Claude Skills — Secondary LANE Windows

Скиллы для **Claude Code** (Anthropic CLI).

> Если ты используешь **OpenAI Codex** (ChatGPT) — смотри папку
> [`../codex-skills/`](../codex-skills/README.md).

## Статус

Скилл для автоматизированной установки на Windows через Claude Code
**в разработке**. Ожидается в следующем релизе.

До появления скилла для автоматической установки через Claude Code
используй:

- **Codex**: [`../codex-skills/gpts-windows-autopilot/`](../codex-skills/gpts-windows-autopilot/)
- **Вручную**: [`../docs/WINDOWS_FIRST_START.md`](../docs/WINDOWS_FIRST_START.md)

## Ключевое отличие Claude Code от Codex

Claude Code работает **локально** — он имеет прямой доступ к файловой
системе и терминалу. Поэтому когда скилл появится, он будет:

- выполнять команды напрямую (не объяснять, а делать сам)
- проверять результат реально через PowerShell / py
- устранять типовые ошибки без участия пользователя

## Планируемая структура

```
windows-autopilot/          # (ещё не создан)
├── ENTRYPOINT.md
├── SKILL.md
├── agents/
│   └── claude.yaml
├── references/
└── scripts/
    └── run_preflight.py
```
