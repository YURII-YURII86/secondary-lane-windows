#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import token_is_safe

try:
    from tkinter import BOTH, END, LEFT, RIGHT, X, Y, filedialog
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText
except Exception:  # pragma: no cover - runtime fallback for partial Python installs
    BOTH = END = LEFT = RIGHT = X = Y = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    ScrolledText = None  # type: ignore[assignment]
    tk = None  # type: ignore[assignment]


PROJECT_DIR = Path(__file__).resolve().parent
ENV_EXAMPLE_FILE = PROJECT_DIR / ".env.example"
ENV_FILE = PROJECT_DIR / ".env"
STATE_FILE = PROJECT_DIR / ".installer_state.json"
VENV_DIR = PROJECT_DIR / ".venv"
REQUIREMENTS_FILE = PROJECT_DIR / "requirements.txt"
CONTROL_PANEL_FILE = PROJECT_DIR / "gpts_agent_control.py"
LAUNCHER_FILE = PROJECT_DIR / "Запустить GPTS Agent.bat"
DEFAULT_WORKSPACE_ROOT = str(PROJECT_DIR)
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
VENV_UVICORN = VENV_DIR / "Scripts" / "uvicorn.exe"
TOOLS_DIR = PROJECT_DIR / "tools"
LOCAL_NGROK_DIR = TOOLS_DIR / "ngrok"
LOCAL_NGROK_EXE = LOCAL_NGROK_DIR / "ngrok.exe"

PYTHON_DOWNLOAD_URL = "https://www.python.org/downloads/windows/"
NGROK_DOWNLOAD_URL = "https://ngrok.com/download"
NGROK_DIRECT_ZIP_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
NGROK_AUTHTOKEN_URL = "https://dashboard.ngrok.com/tunnels/authtokens"
NGROK_DOMAINS_URL = "https://dashboard.ngrok.com/domains"
WINDOWS_GUIDE_URL = PROJECT_DIR / "docs" / "WINDOWS_FIRST_START.md"
NGROK_MIN_MAJOR_VERSION = 3
WINGET_NGROK_COMMAND = [
    "winget",
    "install",
    "-e",
    "--id",
    "Ngrok.Ngrok",
    "--accept-source-agreements",
    "--accept-package-agreements",
]

INTERNET_CHECK_URLS = (
    "https://www.msftconnecttest.com/connecttest.txt",
    "https://www.google.com/generate_204",
    "https://chatgpt.com",
)

NGROK_DOMAIN_REGEX = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
NGROK_AUTHTOKEN_LINE_RE = re.compile(r"^\s*authtoken\s*:\s*(?P<value>.+?)\s*$", re.IGNORECASE)
PLACEHOLDER_NGROK_DOMAINS = {
    "your-domain.ngrok-free.app",
    "your-domain.ngrok-free.dev",
    "your-domain.ngrok.app",
}
PLACEHOLDER_WORKSPACE_ROOTS = {
    r"c:\secondlane",
    "c:/secondlane",
}

PALETTE = {
    "app_bg": "#eef2f6",
    "surface": "#fbfcfe",
    "panel": "#f3f6f9",
    "border": "#d6dee7",
    "text": "#223042",
    "muted": "#607085",
    "accent": "#335c7d",
    "accent_soft": "#dce7f0",
    "success": "#2f7d57",
    "warning": "#a06a1a",
    "danger": "#b24b4b",
    "shadow": "#e7edf3",
}

STATUS_ICON = {
    "pending": "○",
    "running": "⟳",
    "done": "✓",
    "action": "!",
    "error": "✕",
}

STATUS_TEXT = {
    "pending": "Ожидание",
    "running": "Идёт проверка",
    "done": "Готово",
    "action": "Нужно действие",
    "error": "Ошибка",
}


@dataclass(frozen=True)
class StepSpec:
    key: str
    title: str
    description: str
    why: str


@dataclass(frozen=True)
class InstallHealth:
    needs_repair: bool
    summary: str
    issues: tuple[str, ...]


STEP_SPECS: list[StepSpec] = [
    StepSpec(
        "system",
        "Проверка Windows",
        "Проверяю, что это Windows, есть интернет и можно писать файлы в папку проекта.",
        "Так мы ловим простые проблемы в самом начале, а не оставляем человека с непонятной ошибкой посередине установки.",
    ),
    StepSpec(
        "python",
        "Python 3.13",
        "Проверяю официальный Python 3.13. Это программа, на которой запускается Second Lane.",
        "Нужна одна понятная версия Python, чтобы установка не зависела от случайных старых Python на компьютере.",
    ),
    StepSpec(
        "ngrok",
        "ngrok",
        "Проверяю ngrok. Это программа, которая даёт Second Lane защищённый адрес для связи с ChatGPT.",
        "Без ngrok ChatGPT не сможет достучаться до Second Lane, который работает локально на Windows.",
    ),
    StepSpec(
        "auth",
        "Вход в ngrok",
        "Проверяю ключ ngrok. Ключ подтверждает, что ngrok запускается от твоего аккаунта.",
        "Это один из немногих шагов, где нужен человек: нужно войти в ngrok и вставить ключ.",
    ),
    StepSpec(
        "domain",
        "Адрес ngrok",
        "Проверяю Dev Domain или Domain ngrok. Это постоянный публичный адрес для подключения GPT.",
        "Постоянный адрес нужен, чтобы после перезапуска Windows не приходилось каждый раз заново менять настройки GPT.",
    ),
    StepSpec(
        "env",
        "Файл настроек Second Lane",
        "Создаю .env: адрес ngrok, секретный ключ доступа и папку, к которой можно дать доступ.",
        "Мастер заполняет опасные и технические поля сам, чтобы человек не копировал шаблоны и случайно не открывал лишние папки.",
    ),
    StepSpec(
        "venv",
        "Локальная рабочая папка Python",
        "Создаю отдельное окружение Python и ставлю туда нужные библиотеки.",
        "Так Second Lane не ломает другие программы на Windows и не зависит от чужих библиотек в системе.",
    ),
    StepSpec(
        "finish",
        "Готово",
        "Подсказываю, что нажать дальше, чтобы запустить панель Second Lane.",
        "Последний шаг уже не про установку, а про спокойный запуск и подключение к GPT Actions.",
    ),
]

STEP_BY_KEY = {spec.key: spec for spec in STEP_SPECS}


def internet_available() -> bool:
    for url in INTERNET_CHECK_URLS:
        try:
            result = subprocess.run(
                ["curl.exe", "-fsSL", "--connect-timeout", "5", "--max-time", "10", "-o", "NUL", url],
                cwd=PROJECT_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=12,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return True

    if os.name == "nt" and shutil.which("powershell"):
        script = (
            "$ProgressPreference='SilentlyContinue'; "
            "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; "
            "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri $args[0] | Out-Null; exit 0 } "
            "catch { exit 1 }"
        )
        for url in INTERNET_CHECK_URLS:
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script, url],
                    cwd=PROJECT_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=12,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                return True

    for url in INTERNET_CHECK_URLS:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Second Lane Installer"})
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read(32)
            return True
        except (OSError, TimeoutError, urllib.error.URLError):
            continue
    return False


def normalize_ngrok_token(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    if "ngrok config add-authtoken" in cleaned:
        cleaned = cleaned.split("ngrok config add-authtoken", 1)[1].strip()
    if cleaned.startswith("NGROK_AUTHTOKEN="):
        cleaned = cleaned.split("=", 1)[1].strip()
    parts = cleaned.split()
    if len(parts) > 1:
        cleaned = parts[-1]
    return cleaned.strip().strip("'\"")


def normalize_ngrok_domain(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip().strip("/").lower()


def is_placeholder_ngrok_domain(raw: str) -> bool:
    return normalize_ngrok_domain(raw) in PLACEHOLDER_NGROK_DOMAINS


def ngrok_domain_is_valid(raw: str) -> bool:
    domain = normalize_ngrok_domain(raw)
    if not domain or is_placeholder_ngrok_domain(domain):
        return False
    return bool(NGROK_DOMAIN_REGEX.fullmatch(domain))


def parse_env_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def set_env_value(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    if pattern.search(text):
        # Windows paths contain backslashes like C:\SecondLane.
        # Regex replacement strings treat backslashes as escapes, so use a lambda.
        return pattern.sub(lambda _match: line, text)
    suffix = "" if text.endswith("\n") else "\n"
    return f"{text}{suffix}{line}\n"


def existing_env_text() -> str:
    if ENV_FILE.exists():
        return ENV_FILE.read_text("utf-8-sig")
    if ENV_EXAMPLE_FILE.exists():
        return ENV_EXAMPLE_FILE.read_text("utf-8")
    return ""


def normalize_workspace_root(raw: str) -> str:
    cleaned = raw.strip().strip("'\"")
    if not cleaned:
        return ""
    try:
        return str(Path(cleaned).expanduser())
    except OSError:
        return cleaned


def merge_workspace_roots(primary_root: str, existing_value: str) -> str:
    def canonical(value: str) -> str:
        return normalize_workspace_root(value).rstrip("\\/").lower()

    ordered: list[str] = []
    seen: set[str] = set()
    for item in [primary_root, *existing_value.split(";")]:
        cleaned = normalize_workspace_root(item)
        if not cleaned:
            continue
        key = canonical(cleaned)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ";".join(ordered)


def is_placeholder_workspace_root(raw: str) -> bool:
    first = normalize_workspace_root(raw.split(";", 1)[0]).rstrip("\\/").lower()
    return first in PLACEHOLDER_WORKSPACE_ROOTS


def workspace_placeholder_should_be_ignored(raw: str) -> bool:
    first = normalize_workspace_root(raw.split(";", 1)[0])
    if not is_placeholder_workspace_root(first):
        return False
    return not Path(first).exists()


def run_capture(command: list[str], timeout: int = 20) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    return result.returncode, (result.stdout or "").strip()


def download_file(url: str, destination: Path, timeout: int = 180) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error = ""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Second Lane Installer"})
        with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        return
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        last_error = str(exc)

    if os.name == "nt" and shutil.which("powershell"):
        script = (
            "$ProgressPreference='SilentlyContinue'; "
            "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; "
            "Invoke-WebRequest -UseBasicParsing -Uri $args[0] -OutFile $args[1]"
        )
        try:
            code, output = run_capture(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script, url, str(destination)],
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"не удалось скачать файл: {last_error}; PowerShell: {exc}") from exc
        if code == 0 and destination.exists():
            return
        raise RuntimeError(f"не удалось скачать файл: {last_error}; PowerShell: {output or f'код {code}'}")

    raise RuntimeError(f"не удалось скачать файл: {last_error}")


def ngrok_config_ok(ngrok_path: str) -> tuple[bool, str]:
    authtoken_ok, authtoken_detail = ngrok_authtoken_configured()
    if not authtoken_ok:
        return False, authtoken_detail
    try:
        code, output = run_capture([ngrok_path, "config", "check"], timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"не смог проверить ngrok config: {exc}"
    if code != 0:
        return False, output or "ngrok config check завершился с ошибкой"
    return True, authtoken_detail


def candidate_ngrok_config_files() -> list[Path]:
    raw_paths: list[Path] = []

    ngrok_config_env = os.environ.get("NGROK_CONFIG", "").strip()
    if ngrok_config_env:
        raw_paths.append(Path(ngrok_config_env))

    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        raw_paths.append(Path(local_appdata) / "ngrok" / "ngrok.yml")

    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        raw_paths.append(Path(appdata) / "ngrok" / "ngrok.yml")

    userprofile = os.environ.get("USERPROFILE", "").strip()
    if userprofile:
        profile = Path(userprofile)
        raw_paths.extend(
            [
                profile / "AppData" / "Local" / "ngrok" / "ngrok.yml",
                profile / ".ngrok2" / "ngrok.yml",
            ]
        )

    home = Path.home()
    raw_paths.extend(
        [
            home / "AppData" / "Local" / "ngrok" / "ngrok.yml",
            home / ".ngrok2" / "ngrok.yml",
        ]
    )

    seen: set[str] = set()
    result: list[Path] = []
    for path in raw_paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def config_text_has_ngrok_authtoken(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = NGROK_AUTHTOKEN_LINE_RE.match(line)
        if not match:
            continue
        value = match.group("value").split("#", 1)[0].strip().strip("'\"")
        token = normalize_ngrok_token(value)
        if len(token) >= 20 and " " not in token:
            return True
    return False


def ngrok_authtoken_configured() -> tuple[bool, str]:
    checked: list[str] = []
    for config_path in candidate_ngrok_config_files():
        try:
            if not config_path.exists():
                continue
            checked.append(str(config_path))
            text = config_path.read_text("utf-8", errors="ignore")
        except OSError as exc:
            checked.append(f"{config_path} (не смог прочитать: {exc})")
            continue
        if config_text_has_ngrok_authtoken(text):
            return True, f"authtoken найден в {config_path}"
    if checked:
        return False, "authtoken не найден в найденном ngrok config"
    return False, "файл ngrok config с authtoken пока не найден"


def normalize_exe_path(raw: str) -> str:
    return raw.strip().strip("'\"")


def is_ngrok_exe(path: Path) -> bool:
    try:
        return path.is_file() and path.name.lower() == "ngrok.exe"
    except OSError:
        return False


def ngrok_version_supported(path: str) -> tuple[bool, str]:
    try:
        code, output = run_capture([path, "version"], timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"не смог проверить версию ngrok: {exc}"
    if code != 0:
        return False, output or f"ngrok version завершился с кодом {code}"
    match = re.search(r"ngrok\s+version\s+(\d+)", output, flags=re.IGNORECASE)
    if match and int(match.group(1)) < NGROK_MIN_MAJOR_VERSION:
        return False, f"нужен ngrok v3+, найдено: {output}"
    return True, output or "ngrok version OK"


def usable_ngrok_path(path: Path) -> str | None:
    if not is_ngrok_exe(path):
        return None
    ok, _detail = ngrok_version_supported(str(path))
    if not ok:
        return None
    return str(path)


def configured_ngrok_path() -> str:
    env_values = parse_env_text(existing_env_text())
    return normalize_exe_path(env_values.get("NGROK_PATH", ""))


def iter_common_ngrok_candidates() -> list[Path]:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    user_profile = os.environ.get("USERPROFILE", "")
    candidates = [
        LOCAL_NGROK_EXE,
        Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "ngrok.exe",
        Path(local_appdata) / "ngrok" / "ngrok.exe",
        Path(program_files) / "ngrok" / "ngrok.exe",
        Path(user_profile) / "scoop" / "apps" / "ngrok" / "current" / "ngrok.exe",
        Path(r"C:\ProgramData\chocolatey\bin\ngrok.exe"),
        Path(user_profile) / "Downloads" / "ngrok.exe",
    ]
    for root in (
        Path(local_appdata) / "Microsoft" / "WinGet" / "Packages",
        Path(program_files) / "WinGet" / "Packages",
    ):
        try:
            if root.exists():
                candidates.extend(root.glob("**/ngrok.exe"))
        except OSError:
            continue
    downloads = Path(user_profile) / "Downloads"
    try:
        if downloads.exists():
            candidates.extend(downloads.glob("ngrok*/ngrok.exe"))
    except OSError:
        pass
    return candidates


def find_ngrok_path(preferred_path: str = "") -> str | None:
    for raw in (preferred_path, configured_ngrok_path()):
        cleaned = normalize_exe_path(raw)
        if cleaned:
            candidate = Path(cleaned).expanduser()
            usable = usable_ngrok_path(candidate)
            if usable:
                return usable
    local = usable_ngrok_path(LOCAL_NGROK_EXE)
    if local:
        return local
    found = shutil.which("ngrok")
    if found:
        usable = usable_ngrok_path(Path(found))
        if usable:
            return usable
    for candidate in iter_common_ngrok_candidates():
        usable = usable_ngrok_path(candidate)
        if usable:
            return usable
    return None


def install_ngrok_direct() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "прямая установка ngrok рассчитана на Windows"
    archive_path = TOOLS_DIR / "downloads" / "ngrok-windows-amd64.zip"
    try:
        download_file(NGROK_DIRECT_ZIP_URL, archive_path, timeout=240)
        LOCAL_NGROK_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            member = next((name for name in archive.namelist() if Path(name).name.lower() == "ngrok.exe"), "")
            if not member:
                return False, "в zip-архиве ngrok не найден ngrok.exe"
            with archive.open(member) as src, LOCAL_NGROK_EXE.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        code, output = run_capture([str(LOCAL_NGROK_EXE), "version"], timeout=20)
        if code != 0:
            return False, output or f"ngrok version завершился с кодом {code}"
        return True, f"ngrok скачан и готов: {LOCAL_NGROK_EXE}"
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        return False, str(exc)


def install_ngrok_automatically() -> tuple[bool, str]:
    details: list[str] = []
    ok, detail = install_ngrok_with_winget()
    details.append(f"winget: {detail}")
    if ok:
        ngrok_path = find_ngrok_path()
        if ngrok_path:
            return True, f"ngrok найден после winget: {ngrok_path}"
        details.append("winget завершился, но ngrok.exe пока не найден")

    ok, detail = install_ngrok_direct()
    details.append(f"direct zip: {detail}")
    if ok:
        return True, detail
    return False, "\n".join(details)


def install_ngrok_with_winget() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "автоустановка ngrok через winget доступна только на Windows"
    if shutil.which("winget") is None:
        return False, "winget не найден. Поставь ngrok вручную или через Microsoft Store."
    try:
        code, output = run_capture(WINGET_NGROK_COMMAND, timeout=420)
    except subprocess.TimeoutExpired:
        return False, "winget слишком долго устанавливал ngrok и был остановлен по таймауту"
    except OSError as exc:
        return False, f"не смог запустить winget: {exc}"
    return code == 0, output or f"winget завершился с кодом {code}"


def python_candidates() -> list[list[str]]:
    candidates: list[list[str]] = []
    if sys.executable:
        candidates.append([sys.executable])
    candidates.extend([["py", "-3.13"], ["python"]])
    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for item in candidates:
        key = tuple(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def resolve_python_313() -> list[str] | None:
    for command in python_candidates():
        try:
            code, output = run_capture([*command, "--version"], timeout=6)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if code == 0 and "3.13" in output:
            return command
    return None


def venv_health_check() -> tuple[bool, str]:
    if not VENV_PYTHON.exists():
        return False, "не найден .venv\\Scripts\\python.exe"
    if not VENV_UVICORN.exists():
        return False, "не найден .venv\\Scripts\\uvicorn.exe"
    try:
        code, output = run_capture(
            [
                str(VENV_PYTHON),
                "-c",
                "import fastapi, pydantic, uvicorn; print('ok')",
            ],
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"не смог проверить .venv: {exc}"
    if code != 0 or "ok" not in output:
        detail = output or "импорт зависимостей не прошёл"
        return False, detail
    return True, "ok"


def assess_install_health() -> InstallHealth:
    issues: list[str] = []

    if os.name != "nt":
        issues.append("этот репозиторий и установщик рассчитаны на Windows")

    python_cmd = resolve_python_313()
    if python_cmd is None:
        issues.append("не найден рабочий Python 3.13")

    ngrok_path = find_ngrok_path()
    if ngrok_path is None:
        issues.append("не найден ngrok")
    else:
        ngrok_ok, ngrok_detail = ngrok_config_ok(ngrok_path)
        if not ngrok_ok:
            issues.append(f"ngrok ещё не готов: {ngrok_detail}")

    if not ENV_FILE.exists():
        issues.append("ещё нет файла .env")
    else:
        env_values = parse_env_text(existing_env_text())
        token = env_values.get("AGENT_TOKEN", "")
        if not token_is_safe(token):
            issues.append("AGENT_TOKEN отсутствует или выглядит как заглушка")
        domain = normalize_ngrok_domain(env_values.get("NGROK_DOMAIN", ""))
        if not ngrok_domain_is_valid(domain):
            issues.append("NGROK_DOMAIN не заполнен или выглядит неверно")
        workspace_root = normalize_workspace_root(env_values.get("WORKSPACE_ROOTS", "").split(";", 1)[0])
        if workspace_placeholder_should_be_ignored(workspace_root):
            issues.append("WORKSPACE_ROOTS всё ещё выглядит как шаблон C:\\SecondLane")
        elif not workspace_root:
            issues.append("WORKSPACE_ROOTS не заполнен")
        else:
            workspace_path = Path(workspace_root)
            if not workspace_path.exists():
                issues.append(f"главная папка WORKSPACE_ROOTS не найдена: {workspace_root}")
            elif not workspace_path.is_dir():
                issues.append(f"главный путь WORKSPACE_ROOTS ведёт не в папку: {workspace_root}")

    venv_ok, venv_detail = venv_health_check()
    if not venv_ok:
        issues.append(f".venv не готов: {venv_detail}")

    if issues:
        return InstallHealth(
            needs_repair=True,
            summary="Нашёл несколько вещей, которые лучше автоматически подготовить или починить.",
            issues=tuple(issues),
        )
    return InstallHealth(
        needs_repair=False,
        summary="Похоже, установка уже выглядит здоровой. Можно использовать мастер как перепроверку или быстрый ремонт.",
        issues=(),
    )


class InstallerApp:
    def __init__(self) -> None:
        if tk is None:
            raise RuntimeError("Tkinter недоступен. Нужен полный Python с графическими компонентами.")
        self.root = tk.Tk()
        self.root.title("Secondary LANE Installer")
        self.root.geometry("1280x820")
        self.root.minsize(1080, 720)
        self.root.configure(bg=PALETTE["app_bg"])

        self.status_var = tk.StringVar(value="Готов помочь с установкой или ремонтом")
        self.primary_button_text = tk.StringVar(value="Начать установку")
        self.secondary_button_text = tk.StringVar(value="Что это значит?")
        self.current_step_title_var = tk.StringVar(value="")
        self.current_step_desc_var = tk.StringVar(value="")
        self.current_step_why_var = tk.StringVar(value="")
        self.current_action_hint_var = tk.StringVar(value="")
        self.current_command_var = tk.StringVar(value="Внутреннее действие мастера: —")
        self.ngrok_token_var = tk.StringVar(value="")
        self.ngrok_domain_var = tk.StringVar(value="")
        self.ngrok_path_var = tk.StringVar(value="")
        self.workspace_root_var = tk.StringVar(value=DEFAULT_WORKSPACE_ROOT)
        self.generated_token_var = tk.StringVar(value="")
        self.agent_token_var = tk.StringVar(value="")
        self.current_step_key = STEP_SPECS[0].key
        self.step_status: dict[str, str] = {spec.key: "pending" for spec in STEP_SPECS}
        self.step_vars: dict[str, tk.StringVar] = {
            spec.key: tk.StringVar(value="○ Ожидание") for spec in STEP_SPECS
        }
        self.force_ngrok_auth = False
        self.busy = False
        self.worker_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self._load_state()
        self._build_ui()
        self._announce_initial_health()
        self.root.after(120, self._poll_worker_queue)

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=PALETTE["app_bg"], padx=18, pady=18)
        shell.pack(fill=BOTH, expand=True)

        hero = tk.Frame(shell, bg=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=22, pady=18)
        hero.pack(fill=X, pady=(0, 14))
        tk.Label(hero, text="Secondary LANE Installer", font=("Segoe UI", 21, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            hero,
            text=(
                "Этот мастер делает Windows-установку спокойнее: проверяет Python и ngrok, "
                "создаёт .env, ставит зависимости и оставляет человеку только действительно нужные шаги."
            ),
            font=("Segoe UI", 11),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            wraplength=980,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 10))
        tk.Label(hero, textvariable=self.status_var, font=("Segoe UI", 11, "bold"), bg=PALETTE["surface"], fg=PALETTE["accent"]).pack(anchor="w")

        body = tk.Frame(shell, bg=PALETTE["app_bg"])
        body.pack(fill=BOTH, expand=True)

        left = tk.Frame(body, bg=PALETTE["app_bg"], width=370)
        left.pack(side=LEFT, fill=Y)
        left.pack_propagate(False)

        right = tk.Frame(body, bg=PALETTE["app_bg"])
        right.pack(side=RIGHT, fill=BOTH, expand=True)

        self._build_steps_card(left)
        self._build_actions_card(left)
        self._build_current_step_card(right)
        self._build_log_card(right)
        self._refresh_current_step_card()

    def _build_steps_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=16, pady=16)
        card.pack(fill=X, pady=(0, 12))
        tk.Label(card, text="Что проверяет мастер", font=("Segoe UI", 13, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(card, text="Статусы обновляются сами по мере проверки.", font=("Segoe UI", 10), bg=PALETTE["surface"], fg=PALETTE["muted"]).pack(anchor="w", pady=(4, 10))
        for spec in STEP_SPECS:
            row = tk.Frame(card, bg=PALETTE["panel"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=12, pady=10)
            row.pack(fill=X, pady=4)
            tk.Label(row, text=spec.title, font=("Segoe UI", 10, "bold"), bg=PALETTE["panel"], fg=PALETTE["text"]).pack(anchor="w")
            tk.Label(row, text=spec.description, font=("Segoe UI", 9), bg=PALETTE["panel"], fg=PALETTE["muted"], wraplength=300, justify=LEFT).pack(anchor="w", pady=(2, 4))
            tk.Label(row, textvariable=self.step_vars[spec.key], font=("Segoe UI", 9, "bold"), bg=PALETTE["panel"], fg=PALETTE["accent"]).pack(anchor="w")

    def _build_actions_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=16, pady=16)
        card.pack(fill=BOTH, expand=True)
        tk.Label(card, text="Помощь", font=("Segoe UI", 13, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            card,
            text="Эти кнопки остаются под рукой, но мастер сам скажет, какая нужна сейчас.",
            font=("Segoe UI", 10),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            wraplength=300,
            justify=LEFT,
        ).pack(anchor="w", pady=(4, 12))

        buttons = [
            ("Сбросить мастер и начать заново", self.reset_installer_progress),
            ("Заменить ключ ngrok", self.force_ngrok_token_step),
            ("Открыть большую инструкцию", self.open_guide),
            ("Открыть папку проекта", self.open_project_folder),
            ("Запустить панель", self.launch_control_panel),
        ]
        for title, command in buttons:
            tk.Button(
                card,
                text=title,
                command=command,
                font=("Segoe UI", 10),
                bg=PALETTE["accent_soft"],
                fg=PALETTE["text"],
                activebackground=PALETTE["panel"],
                activeforeground=PALETTE["text"],
                relief="flat",
                bd=0,
                padx=10,
                pady=7,
                cursor="hand2",
            ).pack(fill=X, pady=4)

    def _build_current_step_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=18, pady=16)
        card.pack(fill=X, pady=(0, 12))

        tk.Label(card, text="Что сейчас делает мастер", font=("Segoe UI", 13, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(card, textvariable=self.current_step_title_var, font=("Segoe UI", 16, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w", pady=(12, 0))
        tk.Label(
            card,
            textvariable=self.current_step_desc_var,
            font=("Segoe UI", 10),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            wraplength=780,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            card,
            textvariable=self.current_step_why_var,
            font=("Segoe UI", 9),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            wraplength=780,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))

        self.action_hint_box = tk.Frame(card, bg=PALETTE["panel"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=12, pady=10)
        tk.Label(self.action_hint_box, text="Что нужно сделать", font=("Segoe UI", 10, "bold"), bg=PALETTE["panel"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            self.action_hint_box,
            textvariable=self.current_action_hint_var,
            font=("Segoe UI", 9),
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            wraplength=760,
            justify=LEFT,
        ).pack(anchor="w", pady=(4, 0))

        self.input_frame = tk.Frame(card, bg=PALETTE["surface"])
        self.input_frame.pack(fill=X, pady=(8, 0))

        self.ngrok_token_row = tk.Frame(self.input_frame, bg=PALETTE["surface"])
        tk.Label(self.ngrok_token_row, text="Ключ ngrok", font=("Segoe UI", 10, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            self.ngrok_token_row,
            text="Скопируй длинный authtoken из кабинета ngrok и вставь его сюда.",
            font=("Segoe UI", 9),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            wraplength=760,
            justify=LEFT,
        ).pack(anchor="w", pady=(2, 6))
        token_entry_row = tk.Frame(self.ngrok_token_row, bg=PALETTE["surface"])
        token_entry_row.pack(fill=X)
        self.ngrok_token_entry = tk.Entry(token_entry_row, textvariable=self.ngrok_token_var, font=("Consolas", 10), show="*", relief="solid", bd=1)
        self.ngrok_token_entry.pack(side=LEFT, fill=X, expand=True)
        tk.Button(
            token_entry_row,
            text="Вставить",
            command=self.paste_ngrok_token,
            font=("Segoe UI", 10),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            activebackground=PALETTE["panel"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
        ).pack(side=RIGHT, padx=(8, 0))

        self.ngrok_domain_row = tk.Frame(self.input_frame, bg=PALETTE["surface"])
        tk.Label(self.ngrok_domain_row, text="Адрес ngrok", font=("Segoe UI", 10, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            self.ngrok_domain_row,
            text="Например: my-team.ngrok-free.app или my-team.ngrok-free.dev. Вставляй без https:// и без лишних символов.",
            font=("Segoe UI", 9),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            wraplength=760,
            justify=LEFT,
        ).pack(anchor="w", pady=(2, 6))
        domain_entry_row = tk.Frame(self.ngrok_domain_row, bg=PALETTE["surface"])
        domain_entry_row.pack(fill=X)
        self.ngrok_domain_entry = tk.Entry(domain_entry_row, textvariable=self.ngrok_domain_var, font=("Consolas", 10), relief="solid", bd=1)
        self.ngrok_domain_entry.pack(side=LEFT, fill=X, expand=True)
        tk.Button(
            domain_entry_row,
            text="Вставить",
            command=self.paste_ngrok_domain,
            font=("Segoe UI", 10),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            activebackground=PALETTE["panel"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
        ).pack(side=RIGHT, padx=(8, 0))

        self.ngrok_path_row = tk.Frame(self.input_frame, bg=PALETTE["surface"])
        tk.Label(self.ngrok_path_row, text="Путь к ngrok.exe", font=("Segoe UI", 10, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            self.ngrok_path_row,
            text="Обычно это поле не нужно. Оно появляется только если Windows не смогла сама найти ngrok.",
            font=("Segoe UI", 9),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            wraplength=760,
            justify=LEFT,
        ).pack(anchor="w", pady=(2, 6))
        ngrok_entry_row = tk.Frame(self.ngrok_path_row, bg=PALETTE["surface"])
        ngrok_entry_row.pack(fill=X)
        tk.Entry(ngrok_entry_row, textvariable=self.ngrok_path_var, font=("Consolas", 10), relief="solid", bd=1).pack(side=LEFT, fill=X, expand=True)
        tk.Button(
            ngrok_entry_row,
            text="Выбрать ngrok.exe",
            command=self.choose_ngrok_exe,
            font=("Segoe UI", 10),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            activebackground=PALETTE["panel"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
        ).pack(side=RIGHT, padx=(8, 0))

        self.workspace_row = tk.Frame(self.input_frame, bg=PALETTE["surface"])
        tk.Label(self.workspace_row, text="Главная папка проекта", font=("Segoe UI", 10, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            self.workspace_row,
            text="Это первая папка, к которой GPT получит доступ. Самый безопасный вариант: оставить текущую папку проекта.",
            font=("Segoe UI", 9),
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            wraplength=760,
            justify=LEFT,
        ).pack(anchor="w", pady=(2, 6))
        workspace_entry_row = tk.Frame(self.workspace_row, bg=PALETTE["surface"])
        workspace_entry_row.pack(fill=X)
        entry = tk.Entry(workspace_entry_row, textvariable=self.workspace_root_var, font=("Consolas", 10), relief="solid", bd=1)
        entry.pack(side=LEFT, fill=X, expand=True)
        tk.Button(
            workspace_entry_row,
            text="Выбрать папку",
            command=self.choose_workspace,
            font=("Segoe UI", 10),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            activebackground=PALETTE["panel"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
        ).pack(side=RIGHT, padx=(8, 0))

        self.token_box = tk.Frame(card, bg=PALETTE["panel"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=12, pady=10)
        tk.Label(self.token_box, text="AGENT_TOKEN мастер создаст сам", font=("Segoe UI", 10, "bold"), bg=PALETTE["panel"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            self.token_box,
            text="Это секретный ключ для твоего GPT. После установки он сохранится в .env. Если в проекте уже есть хороший токен, мастер его не сломает.",
            font=("Segoe UI", 9),
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            wraplength=760,
            justify=LEFT,
        ).pack(anchor="w", pady=(2, 6))
        tk.Label(self.token_box, textvariable=self.generated_token_var, font=("Consolas", 10), bg=PALETTE["panel"], fg=PALETTE["text"]).pack(anchor="w")
        tk.Label(
            self.token_box,
            text="Полный AGENT_TOKEN для GPT Actions:",
            font=("Segoe UI", 9, "bold"),
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
        ).pack(anchor="w", pady=(8, 3))
        agent_token_row = tk.Frame(self.token_box, bg=PALETTE["panel"])
        agent_token_row.pack(fill=X)
        self.agent_token_entry = tk.Entry(agent_token_row, textvariable=self.agent_token_var, font=("Consolas", 10), relief="solid", bd=1)
        self.agent_token_entry.pack(side=LEFT, fill=X, expand=True)
        tk.Button(
            agent_token_row,
            text="Скопировать AGENT_TOKEN",
            command=self.copy_agent_token,
            font=("Segoe UI", 10),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            activebackground=PALETTE["surface"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
        ).pack(side=RIGHT, padx=(8, 0))
        tk.Button(
            self.token_box,
            text="Открыть .env",
            command=self.open_env_file,
            font=("Segoe UI", 9),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            activebackground=PALETTE["surface"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2",
        ).pack(anchor="w", pady=(8, 0))

        button_row = tk.Frame(card, bg=PALETTE["surface"])
        button_row.pack(fill=X, pady=(14, 0))
        self.primary_button = tk.Button(
            button_row,
            textvariable=self.primary_button_text,
            command=self.start_install,
            font=("Segoe UI", 11, "bold"),
            bg=PALETTE["accent"],
            fg="white",
            activebackground=PALETTE["text"],
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2",
        )
        self.primary_button.pack(side=LEFT)
        self.secondary_button = tk.Button(
            button_row,
            textvariable=self.secondary_button_text,
            command=self.on_secondary_action,
            font=("Segoe UI", 10),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            activebackground=PALETTE["panel"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.secondary_button.pack(side=LEFT, padx=(10, 0))

        tk.Label(
            card,
            textvariable=self.current_command_var,
            font=("Segoe UI", 9, "bold"),
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            wraplength=780,
            justify=LEFT,
        ).pack(anchor="w", pady=(12, 0))

    def _set_packed(self, widget: tk.Widget, should_show: bool, **pack_options) -> None:
        is_visible = bool(widget.winfo_manager())
        if should_show and not is_visible:
            widget.pack(**pack_options)
        elif not should_show and is_visible:
            widget.pack_forget()

    def _current_step_index(self) -> int:
        for idx, spec in enumerate(STEP_SPECS):
            if spec.key == self.current_step_key:
                return idx
        return 0

    def _refresh_current_step_card(self) -> None:
        idx = self._current_step_index()
        spec = STEP_SPECS[idx]
        status = self.step_status.get(spec.key, "pending")

        self.current_step_title_var.set(f"{idx + 1}. {spec.title}")
        self.current_step_desc_var.set(spec.description)
        self.current_step_why_var.set(f"Зачем: {spec.why}")
        self.current_command_var.set(
            f"Внутреннее действие мастера: {spec.title} — {STATUS_TEXT.get(status, 'Ожидание')}"
        )

        show_hint = False
        hint = ""
        show_token = False
        show_domain = False
        show_ngrok_path = False
        show_workspace = False
        show_token_box = spec.key in {"env", "finish"}

        self.secondary_button_text.set("Что это значит?")
        if self.busy:
            self.primary_button_text.set("Работаю...")
        elif status == "action":
            show_hint = True
            if spec.key == "system":
                hint = (
                    "Мастер не смог уверенно проверить базовые вещи. Если сайты в браузере открываются, "
                    "просто нажми «Проверить снова». Если ошибка повторится, открой журнал ниже и скопируй его."
                )
                self.primary_button_text.set("Проверить снова")
                self.secondary_button_text.set("Открыть ChatGPT")
            elif spec.key == "python":
                hint = (
                    "Нужен официальный Python 3.13 для Windows. Нажми «Открыть Python 3.13», "
                    "скачай Windows installer 64-bit и при установке включи Add python.exe to PATH."
                )
                self.primary_button_text.set("Проверить Python снова")
                self.secondary_button_text.set("Открыть Python 3.13")
            elif spec.key == "ngrok":
                hint = (
                    "Мастер уже попробовал поставить ngrok автоматически. Если Windows всё равно его не видит, "
                    "открой ngrok download, распакуй файл и выбери ngrok.exe вручную ниже."
                )
                show_ngrok_path = True
                self.primary_button_text.set("Проверить ngrok снова")
                self.secondary_button_text.set("Открыть ngrok download")
            elif spec.key == "auth":
                hint = (
                    "Нужно одно ручное действие: получить ключ ngrok и вставить его в поле ниже. "
                    "Открой страницу authtoken, скопируй длинный ключ целиком и нажми «Сохранить ключ и продолжить»."
                )
                show_token = True
                self.primary_button_text.set("Сохранить ключ и продолжить")
                self.secondary_button_text.set("Открыть authtoken")
            elif spec.key == "domain":
                hint = (
                    "Вставь Dev Domain или Domain ngrok. Он выглядит примерно так: my-team.ngrok-free.app, "
                    "my-team.ngrok-free.dev или my-team.ngrok.app. Если адреса ещё нет, открой страницу Domains."
                )
                show_domain = True
                self.primary_button_text.set("Сохранить адрес и продолжить")
                self.secondary_button_text.set("Открыть domains")
            elif spec.key == "env":
                hint = (
                    "Проверь главную папку проекта. Это папка, которую GPT сможет видеть. "
                    "Для безопасного простого старта лучше оставить текущую папку проекта."
                )
                show_workspace = True
                show_token_box = True
                self.primary_button_text.set("Сохранить папку и продолжить")
                self.secondary_button_text.set("Выбрать папку")
            else:
                hint = "Мастер остановился, чтобы не делать опасных догадок. Посмотри журнал ниже и нажми «Попробовать снова»."
                self.primary_button_text.set("Попробовать снова")
        elif spec.key == "finish" and status == "done":
            show_hint = True
            hint = (
                "Установка завершена. Нажми «Запустить панель», дождись строки про активный туннель "
                "и только после этого подключай openapi.gpts.yaml в GPT Actions."
            )
            show_token_box = True
            self.primary_button_text.set("Запустить панель")
            self.secondary_button_text.set("Открыть инструкцию")
        else:
            if status == "error":
                show_hint = True
                hint = "Этот шаг завершился ошибкой. Посмотри журнал ниже и нажми «Попробовать снова»."
                self.primary_button_text.set("Попробовать снова")
            elif idx == 0 and status == "pending":
                self.primary_button_text.set("Начать установку")
            else:
                self.primary_button_text.set("Продолжить")

        self.current_action_hint_var.set(hint)
        self._set_packed(self.action_hint_box, show_hint, fill=X, pady=(12, 4), before=self.input_frame)
        self._set_packed(self.ngrok_token_row, show_token, fill=X, pady=(8, 4))
        self._set_packed(self.ngrok_domain_row, show_domain, fill=X, pady=(8, 4))
        self._set_packed(self.ngrok_path_row, show_ngrok_path, fill=X, pady=(8, 4))
        self._set_packed(self.workspace_row, show_workspace, fill=X, pady=(8, 4))
        self._set_packed(self.token_box, show_token_box, fill=X, pady=(12, 0), before=self.primary_button.master)

        button_state = "disabled" if self.busy else "normal"
        self.primary_button.configure(state=button_state)
        self.secondary_button.configure(state=button_state)

    def paste_ngrok_token(self) -> None:
        text = normalize_ngrok_token(self._clipboard_text())
        if not text:
            self.write_log("В буфере обмена не вижу ключ ngrok. Сначала скопируй authtoken на сайте ngrok.\n")
            return
        self.ngrok_token_var.set(text)
        self.ngrok_token_entry.focus_set()
        self.ngrok_token_entry.icursor(END)

    def paste_ngrok_domain(self) -> None:
        text = normalize_ngrok_domain(self._clipboard_text())
        if not text:
            self.write_log("В буфере обмена не вижу адрес ngrok. Сначала скопируй Dev Domain или Domain в кабинете ngrok.\n")
            return
        self.ngrok_domain_var.set(text)
        self.ngrok_domain_entry.focus_set()
        self.ngrok_domain_entry.icursor(END)

    def _clipboard_text(self) -> str:
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return ""

    def copy_agent_token(self) -> None:
        token = self.agent_token_var.get().strip()
        if not token:
            env_token = parse_env_text(existing_env_text()).get("AGENT_TOKEN", "")
            if token_is_safe(env_token):
                token = env_token
                self.agent_token_var.set(token)
                self.generated_token_var.set("AGENT_TOKEN найден в .env. Его можно вставлять в GPT Actions.")
        if not token_is_safe(token):
            self.write_log("AGENT_TOKEN ещё не создан. Дай мастеру завершить шаг файла настроек Second Lane.\n")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(token)
        self.status_var.set("AGENT_TOKEN скопирован")
        self.write_log("AGENT_TOKEN скопирован в буфер обмена. В GPT Actions вставляй его как Bearer API key.\n")

    def open_env_file(self) -> None:
        if not ENV_FILE.exists():
            self.write_log("Файл .env пока не создан. Дай мастеру завершить шаг файла настроек Second Lane.\n")
            return
        try:
            if os.name == "nt":
                os.startfile(str(ENV_FILE))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(ENV_FILE)], cwd=PROJECT_DIR)
            else:
                subprocess.Popen(["xdg-open", str(ENV_FILE)], cwd=PROJECT_DIR)
            self.write_log("Открыл файл .env.\n")
        except Exception as exc:
            self.write_log(f"Не смог открыть .env автоматически: {exc}\n")

    def on_secondary_action(self) -> None:
        key = self.current_step_key
        status = self.step_status.get(key, "pending")
        if status != "action" and not (key == "finish" and status == "done"):
            self.write_log(f"{STEP_BY_KEY.get(key, STEP_SPECS[0]).title}: {STEP_BY_KEY.get(key, STEP_SPECS[0]).why}\n")
            return
        if key == "system":
            self.open_external("https://chatgpt.com")
        elif key == "python":
            self.open_external(PYTHON_DOWNLOAD_URL)
        elif key == "ngrok":
            self.open_external(NGROK_DOWNLOAD_URL)
        elif key == "auth":
            self.open_external(NGROK_AUTHTOKEN_URL)
        elif key == "domain":
            self.open_external(NGROK_DOMAINS_URL)
        elif key == "env":
            self.choose_workspace()
        elif key == "finish":
            self.open_guide()
        else:
            self.open_guide()

    def _build_log_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1, padx=16, pady=14)
        card.pack(fill=BOTH, expand=True)
        top = tk.Frame(card, bg=PALETTE["surface"])
        top.pack(fill=X, pady=(0, 8))
        tk.Label(top, text="Журнал установки", font=("Segoe UI", 13, "bold"), bg=PALETTE["surface"], fg=PALETTE["text"]).pack(side=LEFT)
        tk.Button(
            top,
            text="Очистить",
            command=lambda: self.log.delete("1.0", END),
            font=("Segoe UI", 9),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2",
        ).pack(side=RIGHT)
        self.log = ScrolledText(
            card,
            height=18,
            wrap="word",
            font=("Consolas", 10),
            bg=PALETTE["panel"],
            fg=PALETTE["text"],
            relief="flat",
            borderwidth=0,
            insertbackground=PALETTE["text"],
        )
        self.log.pack(fill=BOTH, expand=True)
        self.log.configure(highlightthickness=1, highlightbackground=PALETTE["border"], highlightcolor=PALETTE["accent"])
        self.write_log("Мастер запускается...\n")

    def _load_state(self) -> None:
        env_values = parse_env_text(existing_env_text())
        saved_domain = ""
        saved_workspace = DEFAULT_WORKSPACE_ROOT
        saved_ngrok_path = ""
        if STATE_FILE.exists():
            try:
                import json

                payload = json.loads(STATE_FILE.read_text("utf-8"))
                saved_domain = str(payload.get("ngrok_domain", "")).strip()
                saved_workspace = str(payload.get("workspace_root", DEFAULT_WORKSPACE_ROOT)).strip() or DEFAULT_WORKSPACE_ROOT
                saved_ngrok_path = str(payload.get("ngrok_path", "")).strip()
            except Exception:
                pass
        env_domain = normalize_ngrok_domain(env_values.get("NGROK_DOMAIN", ""))
        env_workspace = env_values.get("WORKSPACE_ROOTS", "").split(";", 1)[0].strip()
        if workspace_placeholder_should_be_ignored(env_workspace):
            env_workspace = ""
        env_ngrok_path = normalize_exe_path(env_values.get("NGROK_PATH", ""))
        self.ngrok_domain_var.set(env_domain if env_domain and not is_placeholder_ngrok_domain(env_domain) else saved_domain)
        self.ngrok_path_var.set(env_ngrok_path or saved_ngrok_path)
        self.workspace_root_var.set(env_workspace or saved_workspace)
        token = env_values.get("AGENT_TOKEN", "")
        if token_is_safe(token):
            self.agent_token_var.set(token)
            self.generated_token_var.set("AGENT_TOKEN уже есть. Его можно скопировать кнопкой ниже.")
        else:
            self.agent_token_var.set("")
            self.generated_token_var.set("Новый токен будет создан автоматически во время установки")

    def _save_state(self) -> None:
        try:
            import json

            payload = {
                "ngrok_domain": normalize_ngrok_domain(self.ngrok_domain_var.get()),
                "ngrok_path": normalize_exe_path(self.ngrok_path_var.get()),
                "workspace_root": self.workspace_root_var.get().strip(),
            }
            STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    def _announce_initial_health(self) -> None:
        health = assess_install_health()
        self.status_var.set(health.summary)
        self.write_log(f"{health.summary}\n")
        if health.issues:
            self.write_log("Что именно вижу сейчас:\n")
            for issue in health.issues:
                self.write_log(f"- {issue}\n")
            self.write_log(
                "\nНажми «Начать установку».\n"
                "Мастер постарается сам довести состояние до рабочего.\n"
            )
        else:
            for spec in STEP_SPECS:
                self.step_status[spec.key] = "done"
                self.step_vars[spec.key].set("✓ Готово")
            self.current_step_key = "finish"
            self.write_log(
                "Критичных проблем не вижу.\n"
                "Можешь использовать кнопку как перепроверку или быстрый repair-pass.\n"
            )
        self._refresh_current_step_card()

    def _poll_worker_queue(self) -> None:
        should_refresh = False
        while True:
            try:
                kind, payload = self.worker_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log.insert(END, payload)
                self.log.see(END)
            elif kind == "status":
                self.status_var.set(payload)
            elif kind == "agent_token":
                self.agent_token_var.set(payload)
            elif kind == "token_status":
                self.generated_token_var.set(payload)
            elif kind.startswith("step:"):
                _, key = kind.split(":", 1)
                self.step_vars[key].set(payload)
                should_refresh = True
            elif kind.startswith("step_state:"):
                _, key = kind.split(":", 1)
                self.step_status[key] = payload
                if payload in {"running", "action", "error"}:
                    self.current_step_key = key
                elif payload == "done":
                    if key == "finish":
                        self.current_step_key = key
                    elif self.current_step_key == key:
                        next_idx = min(self._current_step_index() + 1, len(STEP_SPECS) - 1)
                        self.current_step_key = STEP_SPECS[next_idx].key
                should_refresh = True
            elif kind == "busy":
                self.busy = payload == "1"
                should_refresh = True
        if should_refresh:
            self._refresh_current_step_card()
        self.root.after(120, self._poll_worker_queue)

    def write_log(self, text: str) -> None:
        self.worker_queue.put(("log", text if text.endswith("\n") else f"{text}\n"))

    def set_status(self, text: str) -> None:
        self.worker_queue.put(("status", text))

    def set_step(self, key: str, status: str, detail: str = "") -> None:
        text = f"{STATUS_ICON.get(status, '○')} {detail or STATUS_TEXT.get(status, status)}"
        self.worker_queue.put((f"step_state:{key}", status))
        self.worker_queue.put((f"step:{key}", text))

    def set_agent_token_display(self, token: str, message: str) -> None:
        self.worker_queue.put(("agent_token", token))
        self.worker_queue.put(("token_status", message))

    def choose_workspace(self) -> None:
        initial = self.workspace_root_var.get().strip() or DEFAULT_WORKSPACE_ROOT
        if filedialog is None:
            self.write_log("Не могу открыть системное окно выбора папки: tkinter недоступен.\n")
            return
        picked = filedialog.askdirectory(initialdir=initial if Path(initial).exists() else str(PROJECT_DIR))
        if picked:
            self.workspace_root_var.set(picked)

    def choose_ngrok_exe(self) -> None:
        if filedialog is None:
            self.write_log("Не могу открыть системное окно выбора файла: tkinter недоступен.\n")
            return
        initial = normalize_exe_path(self.ngrok_path_var.get())
        initial_dir = str(Path(initial).parent) if initial and Path(initial).parent.exists() else str(PROJECT_DIR)
        picked = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Выбери ngrok.exe",
            filetypes=[("ngrok.exe", "ngrok.exe"), ("Executable files", "*.exe"), ("All files", "*.*")],
        )
        if not picked:
            return
        candidate = Path(picked)
        if not is_ngrok_exe(candidate):
            self.write_log("Выбранный файл не похож на ngrok.exe. Проверь имя файла и попробуй ещё раз.\n")
            return
        self.ngrok_path_var.set(str(candidate))
        self._save_state()
        self.write_log(f"Сохранил путь к ngrok.exe: {candidate}\n")

    def open_external(self, url: str) -> None:
        webbrowser.open(url)

    def open_guide(self) -> None:
        target = WINDOWS_GUIDE_URL
        if not target.exists():
            self.write_log("Не нашёл docs/WINDOWS_FIRST_START.md.\n")
            return
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception as exc:
            self.write_log(f"Не смог открыть инструкцию автоматически: {exc}\n")

    def open_project_folder(self) -> None:
        try:
            os.startfile(str(PROJECT_DIR))  # type: ignore[attr-defined]
        except Exception as exc:
            self.write_log(f"Не смог открыть папку проекта: {exc}\n")

    def reset_installer_progress(self) -> None:
        if self.busy:
            self.write_log("Сейчас идёт установка. Дождись окончания шага, потом можно будет сбросить мастер.\n")
            return

        self.force_ngrok_auth = True
        self.current_step_key = STEP_SPECS[0].key
        self.ngrok_token_var.set("")
        self.ngrok_domain_var.set("")
        self.ngrok_path_var.set("")
        self.workspace_root_var.set(DEFAULT_WORKSPACE_ROOT)
        self.agent_token_var.set("")
        self.generated_token_var.set("Новый токен будет создан автоматически во время установки")

        for spec in STEP_SPECS:
            self.step_status[spec.key] = "pending"
            self.step_vars[spec.key].set("○ Ожидание")

        try:
            STATE_FILE.unlink(missing_ok=True)
        except OSError as exc:
            self.write_log(f"Не смог удалить файл прогресса мастера: {exc}\n")

        self.status_var.set("Мастер сброшен. Можно начать установку заново.")
        self.write_log(
            "Сбросил прогресс мастера и очищенные поля ввода.\n"
            "Важно: проект, .env и .venv не удалял. Это безопасный сброс интерфейса.\n"
            "Следующий проход принудительно попросит ключ ngrok, даже если старый ngrok config выглядит заполненным.\n"
        )
        self._refresh_current_step_card()

    def force_ngrok_token_step(self) -> None:
        if self.busy:
            self.write_log("Сейчас идёт установка. Дождись окончания шага, потом можно будет заменить ключ ngrok.\n")
            return

        self.force_ngrok_auth = True
        self.ngrok_token_var.set("")
        self.current_step_key = "auth"
        self.step_status["auth"] = "action"
        self.step_vars["auth"].set("! Вставь authtoken")
        self.status_var.set("Жду новый ключ ngrok")
        self.write_log(
            "Открыл шаг замены ключа ngrok.\n"
            "Вставь актуальный authtoken из кабинета ngrok и нажми «Сохранить ключ и продолжить».\n"
            "Мастер применит новый ключ через ngrok config add-authtoken.\n"
        )
        self._refresh_current_step_card()

    def launch_control_panel(self) -> None:
        if LAUNCHER_FILE.exists():
            try:
                os.startfile(str(LAUNCHER_FILE))  # type: ignore[attr-defined]
                self.write_log("Открыл запуск панели.\n")
                return
            except Exception as exc:
                self.write_log(f"Не смог запустить панель через .bat: {exc}\n")
        python_cmd = resolve_python_313()
        if python_cmd is None:
            self.write_log("Сначала нужен Python 3.13 и завершённая установка.\n")
            return
        try:
            subprocess.Popen([*python_cmd, str(CONTROL_PANEL_FILE)], cwd=PROJECT_DIR)
            self.write_log("Запускаю панель напрямую через Python.\n")
        except Exception as exc:
            self.write_log(f"Не смог запустить панель: {exc}\n")

    def start_install(self) -> None:
        if self.busy:
            return
        if self.current_step_key == "finish" and self.step_status.get("finish") == "done":
            self.launch_control_panel()
            return
        self._save_state()
        self.current_step_key = "system"
        self._refresh_current_step_card()
        self.worker_queue.put(("busy", "1"))
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self) -> None:
        for spec in STEP_SPECS:
            self.set_step(spec.key, "pending", "Ожидание")
        step_key = "system"
        try:
            self.set_status("Начинаю проверку")
            step_key = "system"
            if not self._step_system():
                return
            step_key = "python"
            python_cmd = self._step_python()
            if python_cmd is None:
                return
            step_key = "ngrok"
            ngrok_path = self._step_ngrok()
            if ngrok_path is None:
                return
            step_key = "auth"
            if not self._step_auth(ngrok_path):
                return
            step_key = "domain"
            domain = self._step_domain()
            if domain is None:
                return
            step_key = "env"
            token = self._step_env(domain, ngrok_path)
            if token is None:
                return
            step_key = "venv"
            if not self._step_venv(python_cmd):
                return
            step_key = "finish"
            self._step_finish(token)
        except Exception as exc:
            self.set_step(step_key, "error", "Мастер остановился")
            self.set_status("Мастер остановился на ошибке")
            self.write_log(
                "Мастер поймал ошибку и остановился безопасно.\n"
                f"Шаг: {STEP_BY_KEY.get(step_key, STEP_SPECS[0]).title}\n"
                f"Техническая причина: {exc}\n"
            )
        finally:
            self.worker_queue.put(("busy", "0"))

    def _step_system(self) -> bool:
        self.set_step("system", "running", "Проверяю")
        self.set_status("Проверяю базовые вещи")
        if os.name != "nt":
            self.set_step("system", "error", "Нужна Windows")
            self.set_status("Этот мастер рассчитан на Windows")
            self.write_log("Этот установщик рассчитан именно на Windows 10/11.\n")
            return False
        if not internet_available():
            self.set_step("system", "action", "Нужен интернет")
            self.set_status("Жду интернет")
            self.write_log(
                "Не вижу стабильный интернет.\n"
                "Проверь, что браузер открывает обычные сайты, и нажми кнопку ещё раз.\n"
            )
            return False
        try:
            with tempfile.NamedTemporaryFile(dir=PROJECT_DIR, prefix="sl-installer-", delete=True):
                pass
        except OSError as exc:
            self.set_step("system", "error", "Нет прав записи")
            self.set_status("Не могу писать в папку проекта")
            self.write_log(f"Не могу создать временный файл в папке проекта: {exc}\n")
            return False
        self.set_step("system", "done", "Windows и папка в порядке")
        self.write_log("Проверка системы пройдена.\n")
        return True

    def _step_python(self) -> list[str] | None:
        self.set_step("python", "running", "Проверяю")
        self.set_status("Проверяю Python 3.13")
        command = resolve_python_313()
        if command is None:
            self.set_step("python", "action", "Поставь Python 3.13")
            self.set_status("Жду установку Python")
            self.write_log(
                "Не нашёл рабочий Python 3.13.\n"
                "Что сделать сейчас:\n"
                "1. Нажми «Открыть Python 3.13».\n"
                "2. Поставь Windows installer 64-bit.\n"
                "3. Во время установки обязательно включи «Add python.exe to PATH».\n"
                "4. Если мастер не открылся сам после установки, просто снова запусти этот же установщик.\n"
            )
            return None
        self.set_step("python", "done", f"Найден: {' '.join(command)}")
        self.write_log(f"Python 3.13 найден: {' '.join(command)}\n")
        return command

    def _step_ngrok(self) -> str | None:
        self.set_step("ngrok", "running", "Проверяю")
        self.set_status("Проверяю ngrok")
        ngrok_path = find_ngrok_path(self.ngrok_path_var.get())
        if ngrok_path is None:
            self.write_log("Не нашёл ngrok. Пробую поставить автоматически: сначала winget, потом прямой zip от ngrok.\n")
            ok, detail = install_ngrok_automatically()
            if ok:
                ngrok_path = find_ngrok_path(self.ngrok_path_var.get())
                if ngrok_path is not None:
                    self.ngrok_path_var.set(ngrok_path)
                    self._save_state()
                    self.set_step("ngrok", "done", f"Найден: {ngrok_path}")
                    self.write_log(f"ngrok найден после автоустановки: {ngrok_path}\n")
                    return ngrok_path
                self.write_log(
                    "Автоустановка завершилась успешно, но мастер пока не видит ngrok.exe.\n"
                    "Обычно помогает закрыть и открыть мастер заново. Если нет — укажи файл через «Выбрать ngrok.exe».\n"
                )
            else:
                self.write_log(f"Автоустановка ngrok не сработала: {detail[:1200]}\n")
            self.set_step("ngrok", "action", "Поставь или выбери ngrok.exe")
            self.set_status("Жду ngrok")
            self.write_log(
                "Что сделать сейчас:\n"
                "1. Нажми «Открыть ngrok download» и скачай Windows-версию.\n"
                "2. Если скачался zip, распакуй его и нажми «Выбрать ngrok.exe».\n"
                "3. Потом снова нажми главную кнопку.\n"
            )
            self.open_external(NGROK_DOWNLOAD_URL)
            return None
        self.ngrok_path_var.set(ngrok_path)
        self._save_state()
        self.set_step("ngrok", "done", f"Найден: {ngrok_path}")
        self.write_log(f"ngrok найден: {ngrok_path}\n")
        return ngrok_path

    def _step_auth(self, ngrok_path: str) -> bool:
        self.set_step("auth", "running", "Проверяю")
        self.set_status("Проверяю ключ ngrok")
        authtoken = normalize_ngrok_token(self.ngrok_token_var.get())
        if not authtoken:
            ok, detail = ngrok_config_ok(ngrok_path)
            if ok:
                self.write_log(
                    "В ngrok config уже есть authtoken, но мастер больше не пропускает этот шаг молча.\n"
                    "Если первый проход был кривым или ключ надо заменить, вставь актуальный authtoken заново.\n"
                )
            elif detail and "authentication failed" not in detail.lower() and "invalid authtoken" not in detail.lower():
                self.write_log(f"Текущий ngrok config ещё не готов: {detail}\n")
            self.set_step("auth", "action", "Вставь authtoken")
            self.set_status("Жду authtoken")
            self.write_log(
                "Нужен ключ ngrok.\n"
                "Что сделать сейчас:\n"
                "1. Нажми «Открыть authtoken».\n"
                "2. Скопируй authtoken из кабинета ngrok.\n"
                "3. Вставь его в поле ключа, которое показал мастер.\n"
                "4. Снова нажми главную кнопку.\n"
            )
            return False
        if len(authtoken) < 20:
            self.set_step("auth", "action", "Authtoken выглядит слишком коротким")
            self.set_status("Проверь authtoken")
            self.write_log(
                "Похоже, в поле authtoken попал слишком короткий текст.\n"
                "Обычно туда нужно вставить длинное значение целиком из кабинета ngrok.\n"
            )
            return False

        self.write_log("Пробую привязать authtoken к ngrok...\n")
        try:
            code, output = run_capture([ngrok_path, "config", "add-authtoken", authtoken], timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.set_step("auth", "error", "Ошибка привязки")
            self.set_status("Не смог сохранить authtoken")
            self.write_log(f"Не смог выполнить ngrok config add-authtoken: {exc}\n")
            return False
        if code != 0:
            self.set_step("auth", "action", "Проверь authtoken")
            self.set_status("Authtoken не принят")
            self.write_log(
                "ngrok не принял authtoken.\n"
                f"Что ответил ngrok:\n{output or '(пустой вывод)'}\n"
                "Проверь, что ты скопировал токен полностью, без лишних слов.\n"
            )
            return False

        self.set_step("auth", "done", "Authtoken сохранён")
        self.force_ngrok_auth = False
        self.write_log("Authtoken сохранён в конфиг ngrok.\n")
        return True

    def _step_domain(self) -> str | None:
        self.set_step("domain", "running", "Проверяю")
        self.set_status("Проверяю домен ngrok")
        domain = normalize_ngrok_domain(self.ngrok_domain_var.get())
        if not domain or is_placeholder_ngrok_domain(domain):
            self.set_step("domain", "action", "Вставь адрес ngrok")
            self.set_status("Жду домен ngrok")
            self.write_log(
                "Пока не вижу реальный Dev Domain или Domain ngrok.\n"
                "Что сделать сейчас:\n"
                "1. Нажми «Открыть domains».\n"
                "2. Скопируй свой бесплатный Dev Domain или созданный Domain.\n"
                "3. Вставь его в поле адреса, которое показал мастер, без https://.\n"
                "4. Снова нажми главную кнопку.\n"
            )
            return None
        if not ngrok_domain_is_valid(domain):
            self.set_step("domain", "action", "Формат домена странный")
            self.set_status("Проверь домен ngrok")
            self.write_log(
                "Домен выглядит необычно.\n"
                "Ожидаю что-то вроде example-name.ngrok-free.app, example-name.ngrok-free.dev или team-name.ngrok.app.\n"
            )
            return None
        self.ngrok_domain_var.set(domain)
        self.set_step("domain", "done", domain)
        self.write_log(f"Домен принят: {domain}\n")
        return domain

    def _step_env(self, domain: str, ngrok_path: str) -> str | None:
        self.set_step("env", "running", "Создаю")
        self.set_status("Заполняю .env")
        workspace_root = normalize_workspace_root(self.workspace_root_var.get()) or DEFAULT_WORKSPACE_ROOT
        if ";" in workspace_root:
            self.set_step("env", "action", "Укажи одну главную папку")
            self.set_status("Проверь главную папку проекта")
            self.write_log(
                "В поле главной папки сейчас несколько путей через `;`.\n"
                "Для простого режима сюда лучше вставлять только одну основную папку.\n"
                "Если в .env уже были дополнительные папки, мастер сохранит их сам.\n"
            )
            return None
        workspace_path = Path(workspace_root)
        if not workspace_path.exists():
            self.set_step("env", "action", "Папка не найдена")
            self.set_status("Проверь папку проекта")
            self.write_log(
                "Указанная главная папка не существует.\n"
                f"Сейчас вижу: {workspace_root}\n"
                "Выбери существующую папку и снова нажми главную кнопку.\n"
            )
            return None
        if not workspace_path.is_dir():
            self.set_step("env", "action", "Нужна именно папка")
            self.set_status("Проверь путь проекта")
            self.write_log(
                "Главный путь должен вести в папку, а не в отдельный файл.\n"
                f"Сейчас вижу: {workspace_root}\n"
            )
            return None
        env_text = existing_env_text()
        if not env_text:
            self.set_step("env", "error", "Нет .env.example")
            self.set_status("Не нашёл шаблон .env")
            self.write_log("Не нашёл .env.example, поэтому не могу безопасно собрать .env.\n")
            return None

        current_values = parse_env_text(env_text)
        token = current_values.get("AGENT_TOKEN", "")
        if not token_is_safe(token):
            token = secrets.token_urlsafe(48)
        self.set_agent_token_display(token, "AGENT_TOKEN создан. После записи в .env нажми «Скопировать AGENT_TOKEN».")
        existing_workspace_roots = current_values.get("WORKSPACE_ROOTS", "")
        if not ENV_FILE.exists() or is_placeholder_workspace_root(existing_workspace_roots):
            existing_workspace_roots = ""
        merged_workspace_roots = merge_workspace_roots(workspace_root, existing_workspace_roots)

        env_text = set_env_value(env_text, "AGENT_TOKEN", token)
        env_text = set_env_value(env_text, "AGENT_HOST", "127.0.0.1")
        env_text = set_env_value(env_text, "AGENT_PORT", "8787")
        env_text = set_env_value(env_text, "WORKSPACE_ROOTS", merged_workspace_roots)
        env_text = set_env_value(env_text, "ENABLED_PROVIDER_MANIFESTS", str(PROJECT_DIR / "app" / "providers"))
        env_text = set_env_value(env_text, "STATE_DB_PATH", str(PROJECT_DIR / "data" / "agent.db"))
        env_text = set_env_value(env_text, "NGROK_DOMAIN", domain)
        env_text = set_env_value(env_text, "NGROK_PATH", ngrok_path)

        try:
            ENV_FILE.write_text(env_text, "utf-8")
        except OSError as exc:
            self.set_step("env", "error", "Не смог записать")
            self.set_status("Не могу сохранить .env")
            self.write_log(f"Не смог сохранить .env: {exc}\n")
            return None

        self.set_agent_token_display(token, "AGENT_TOKEN сохранён в .env. Его можно скопировать кнопкой ниже.")
        self.set_step("env", "done", ".env обновлён")
        self.write_log(
            ".env готов.\n"
            f"WORKSPACE_ROOTS начинается с: {workspace_root}\n"
            f"Итоговый список WORKSPACE_ROOTS: {merged_workspace_roots}\n"
            f"NGROK_PATH сохранён: {ngrok_path}\n"
            "AGENT_TOKEN сохранён автоматически.\n"
        )
        return token

    def _step_venv(self, python_cmd: list[str]) -> bool:
        self.set_step("venv", "running", "Ставлю зависимости")
        self.set_status("Готовлю рабочее окружение Python")
        venv_ok, venv_detail = venv_health_check()
        if venv_ok:
            self.set_step("venv", "done", "Окружение уже готово")
            self.write_log("Готовое и рабочее окружение уже найдено, заново не пересобираю.\n")
            return True
        if VENV_DIR.exists():
            self.write_log(
                "Нашёл .venv, но оно выглядит неполным или сломанным.\n"
                f"Причина: {venv_detail}\n"
                "Удаляю старое окружение и пересобираю его с нуля.\n"
            )
            try:
                shutil.rmtree(VENV_DIR)
            except OSError as exc:
                self.set_step("venv", "error", "Не смог очистить старую .venv")
                self.set_status("Закрой процессы, которые держат .venv")
                self.write_log(
                    "Не смог удалить старое окружение.\n"
                    f"Техническая причина: {exc}\n"
                    "Закрой открытые окна панели, терминалы, VS Code или антивирусный lock и попробуй ещё раз.\n"
                )
                return False

        self.write_log(f"Создаю .venv через {' '.join(python_cmd)} -m venv ...\n")
        try:
            code, output = run_capture([*python_cmd, "-m", "venv", str(VENV_DIR)], timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.set_step("venv", "error", "Не смог создать .venv")
            self.set_status("Ошибка создания .venv")
            self.write_log(f"Не смог создать .venv: {exc}\n")
            return False
        if code != 0:
            self.set_step("venv", "error", "venv завершился с ошибкой")
            self.set_status("Ошибка при создании .venv")
            self.write_log(f"Вывод venv:\n{output or '(пусто)'}\n")
            return False

        pip_bin = VENV_DIR / "Scripts" / "pip.exe"
        self.write_log("Устанавливаю зависимости из requirements.txt...\n")
        try:
            proc = subprocess.Popen(
                [str(pip_bin), "install", "-r", str(REQUIREMENTS_FILE)],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            self.set_step("venv", "error", "Не смог запустить pip")
            self.set_status("Ошибка запуска pip")
            self.write_log(f"Не смог запустить pip: {exc}\n")
            return False

        assert proc.stdout is not None
        for line in proc.stdout:
            short = line.rstrip()
            if short:
                self.write_log(f"[pip] {short}\n")
        return_code = proc.wait()
        if return_code != 0:
            self.set_step("venv", "error", "pip завершился с ошибкой")
            self.set_status("Не удалось поставить зависимости")
            self.write_log(
                "Установка зависимостей не завершилась.\n"
                "Чаще всего причина простая: интернет, прокси, корпоративная защита или временный сбой PyPI.\n"
            )
            return False

        final_ok, final_detail = venv_health_check()
        if not final_ok:
            self.set_step("venv", "error", "Окружение собрано, но не ожило")
            self.set_status("Проблема внутри .venv")
            self.write_log(
                "После установки зависимостей окружение всё ещё не прошло проверку.\n"
                f"Что именно не так: {final_detail}\n"
            )
            return False

        self.set_step("venv", "done", ".venv готов")
        self.write_log("Зависимости установлены. Окружение готово.\n")
        return True

    def _step_finish(self, token: str) -> None:
        self.set_agent_token_display(token, "AGENT_TOKEN готов. Скопируй его для Bearer auth в GPT Actions.")
        self.set_step("finish", "done", "Можно запускать")
        self.set_status("Установка завершена")
        self.write_log(
            "Установка завершена.\n"
            "Что дальше:\n"
            "1. Сейчас сам попробую открыть панель.\n"
            "2. Дождись строки «Туннель активен».\n"
            "3. Только потом импортируй openapi.gpts.yaml в GPT Actions.\n"
            "4. Для Bearer auth нажми «Скопировать AGENT_TOKEN» и вставь полный ключ в ChatGPT.\n"
        )
        self.launch_control_panel()

    def run(self) -> None:
        self.root.mainloop()


def installer_self_check() -> int:
    if tk is None:
        print("Tkinter is not available. Install the full Python 3.13 Windows installer from python.org.")
        return 1
    try:
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
    except Exception as exc:
        print(f"Tkinter smoke check failed: {exc}")
        return 1
    print("installer self-check ok")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--needs-repair", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args, _ = parser.parse_known_args()

    if args.self_check:
        raise SystemExit(installer_self_check())

    if args.needs_repair:
        raise SystemExit(1 if assess_install_health().needs_repair else 0)

    InstallerApp().run()
