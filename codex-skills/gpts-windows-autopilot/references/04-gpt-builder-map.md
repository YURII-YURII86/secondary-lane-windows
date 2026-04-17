# GPT Builder Map

Use this when guiding the user through ChatGPT.

> **Paths:** the fragment shown as `<branch>/` below means the branch root
> returned by `discover_secondarylane_layout.py` / `_common.find_branch_root`.
> Do NOT hardcode `Версия для Виндовс/` — the user may have unpacked under
> `C:\SecondLane\`, `Downloads\secondary-lane-windows\` or any other name.
> Always substitute the real discovered path before showing it to the user.

## Main mapping

### Instructions

Source:

- `<branch>/gpts/system_instructions.txt`

Destination in ChatGPT:

- `Instructions`

### Knowledge

Source:

- all `.md` files from `<branch>/gpts/knowledge/` and its subfolders

Destination in ChatGPT:

- `Knowledge`

### Actions schema

Source:

- `<branch>/openapi.gpts.yaml`

Destination in ChatGPT:

- `Actions`

## Important do-not-confuse rules

- `Instructions` is for text from `system_instructions.txt`
- `Knowledge` is for uploading knowledge files
- `Actions` is for the schema from `openapi.gpts.yaml`

Do not tell the user to:

- paste knowledge files into `Instructions`
- upload the YAML into `Knowledge`
- edit the YAML manually

## Auth map

### What the user sees in ChatGPT

In the GPT editor → `Actions` → `Authentication`:

- choose `API Key`
- `Auth Type` = `Bearer`
- `API Key` = **только значение токена** (строка после `AGENT_TOKEN=` в `.env`)

### Plain-language explanation to give the user

> «Bearer-токен — это просто пароль, который агент на твоём компьютере
> ждёт в каждом запросе от ChatGPT. В `.env` он записан в виде
> `AGENT_TOKEN=длинная_строка`. В ChatGPT нужно вставить только эту
> длинную строку — без слова `Bearer`, без знака `=`, без кавычек.
> ChatGPT сам добавит `Bearer ` в начало при отправке».

Source:

- the value part of `AGENT_TOKEN=...` from `.env` (everything right of the `=`)

Destination:

- `API Key` field in the ChatGPT action setup (with `Auth Type` = `Bearer`)

Primary rule:

- paste **only** the raw token value

Fallback only if the UI explicitly asks for a full header value:

- then paste `Bearer <token>` (with a single space)

Never paste:

- `AGENT_TOKEN=<token>` (the whole `.env` line)
- the value in quotes
- anything with trailing spaces or newlines

## Preview test suggestion

Preferred simple test:

- ask the GPT to call `getCapabilities`

This is safer than starting with a destructive or complex action.
