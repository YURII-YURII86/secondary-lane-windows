# Codex Skills — Secondary LANE Windows

Secondary LANE by **Yurii Slepnev** · Apache-2.0  
Telegram: https://t.me/yurii_yurii86 · YouTube: https://youtube.com/@yurii_yurii86

Скиллы для **OpenAI Codex** (ChatGPT с Codex-режимом).

> Если ты используешь **Claude Code** (Anthropic) — смотри папку
> [`../claude-skills/`](../claude-skills/README.md).

## Что здесь

| Папка | Для чего |
|---|---|
| `gpts-windows-autopilot/` | Почти автоматическая установка Secondary LANE через Codex |

## Как использовать

1. Скопируй папку `gpts-windows-autopilot` в каталог skills своего Codex
2. Скажи Codex:

```text
Установи мне Secondary LANE на Windows по skill-у gpts-windows-autopilot.
Делай всё сам, останавливайся только там, где нужен мой логин,
регистрация, капча, подтверждение почты, оплата или системное разрешение.
```

Если Codex спросит, куда ставить проект:

```text
C:\SecondLane
```

## Что Codex делает сам

- проверяет структуру проекта
- проверяет Python 3.13 и ngrok
- помогает собрать `.env`
- поднимает панель и тоннель
- проверяет `openapi.gpts.yaml`
- проводит через сборку GPT в ChatGPT

## Что Codex не делает без тебя

- регистрация / логин в ngrok и ChatGPT
- капча, подтверждение почты, оплата
- системные разрешения Windows

## Ручная инструкция

Без Codex или для проверки шагов руками:
[`docs/WINDOWS_FIRST_START.md`](../docs/WINDOWS_FIRST_START.md)
