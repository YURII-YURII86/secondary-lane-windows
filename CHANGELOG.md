# Changelog

Secondary LANE by **Yurii Slepnev** · Apache-2.0  
Telegram: https://t.me/yurii_yurii86 · YouTube: https://youtube.com/@yurii_yurii86 · Instagram: https://instagram.com/yurii_yurii86

## RU

### Unreleased

#### Безопасность

- поле `password` в запросе `/v1/ssh/exec` теперь использует `pydantic.SecretStr` — значение маскируется в repr, tracebacks и потенциальных логах
- добавлен in-memory sliding-window rate limiter для `/v1/*` маршрутов (по IP), лимит задаётся переменной `RATE_LIMIT_PER_MINUTE` (по умолчанию 600, `0` отключает)

#### Исправлено

- `ensure_uvicorn` теперь печатает код возврата и последние 15 строк stderr от `venv` и `pip install` — непонятное «не смог подготовить окружение» заменено на диагностику с подсказкой (сеть, прокси, SSL, устаревший pip)
- сужены `except Exception` в `app/core/utils.py:search_text` и `_resolve_python_command` — больше не прячем реальные ошибки сети/диска под общим `Exception`
- Windows smoke diagnostics: action defects и UTF-8 консоль на ru-RU Windows

#### Добавлено

- более сильное публичное позиционирование проекта под именем `Secondary LANE`
- двуязычная рамка README вокруг идеи продолжения работы после лимитов Claude Code / Codex
- служебные документы репозитория: roadmap, contributing guide, security policy и license
- отдельная инструкция `docs/WINDOWS_FIRST_START.md` для первого запуска Windows-версии
- отдельный Windows-мастер `Установить Secondary LANE.bat` + `second_lane_installer.py`, который ведёт человека через Python, ngrok, `.env` и `.venv`

#### Изменено

- README теперь начинается с главного обещания: продолжать реальную работу над проектом в ChatGPT
- README теперь прямо объясняет, что Secondary LANE даёт ChatGPT реальные руки на локальной машине
- README теперь содержит comparison framing, use cases и current status
- документация теперь жёстко фиксирует Python `3.13` как рабочий локальный путь, а repo-local verify/test контур приводит к стандартному `.venv`
- Windows-пакет был ужат: из репозитория убраны non-operational launch/demo/planning-файлы, которые не были нужны для runtime, onboarding, verification или GPT setup
- `Запустить GPTS Agent.bat` теперь сначала отправляет неподготовленную установку в мастер, а не оставляет человека один на один с ручными шагами
- GitHub-репозиторий Windows-версии дополнительно очищен от dev-only skill-папок, тестов, deploy-артефактов и внутренних документов, чтобы скачавший пользователь видел только нужное для установки и работы

## EN

### Unreleased

#### Security

- `password` field on `/v1/ssh/exec` now uses `pydantic.SecretStr` — value is masked in repr, tracebacks, and any future logs
- added in-memory sliding-window rate limiter for `/v1/*` routes (keyed by client IP); limit configurable via `RATE_LIMIT_PER_MINUTE` env var (default 600, `0` disables)

#### Fixed

- `ensure_uvicorn` now surfaces venv/pip return code and the last 15 lines of stderr — the opaque "не смог подготовить окружение" is replaced with actionable diagnostics (network, proxy, SSL, outdated pip)
- narrowed `except Exception` in `app/core/utils.py:search_text` and `_resolve_python_command` — we no longer swallow real disk/network errors under a blanket `Exception`
- Windows smoke diagnostics: action defects and UTF-8 console behavior on ru-RU Windows

#### Added

- stronger public positioning for the project under the name `Secondary LANE`
- bilingual README framing around continuation after Claude Code / Codex limits
- repository metadata docs: roadmap, contributing guide, security policy, and license
- dedicated `docs/WINDOWS_FIRST_START.md` onboarding guide for the Windows-focused build
- a dedicated Windows installer flow via `Установить Secondary LANE.bat` + `second_lane_installer.py` that walks the user through Python, ngrok, `.env`, and `.venv`

#### Changed

- README now leads with the core promise: continue real project work in ChatGPT
- README now explains that Secondary LANE gives ChatGPT real hands on the local machine
- README now includes comparison framing, use cases, and current status
- documentation now explicitly fixes Python `3.13` as the supported local path and standardizes the repo-local verify/test environment around `.venv`
- the Windows package was tightened by removing non-operational launch/demo/planning files that were not needed for runtime, onboarding, verification, or GPT setup
- `Запустить GPTS Agent.bat` now redirects unprepared installs into the installer instead of dropping beginners into manual setup
- the GitHub Windows repo was further cleaned of dev-only skill folders, tests, deploy artifacts, and internal docs so a normal downloader only sees what is needed to install and use the product
