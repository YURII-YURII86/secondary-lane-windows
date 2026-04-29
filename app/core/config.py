# Second Lane
# Copyright (c) 2026 Yurii Slepnev
# Licensed under the Apache License, Version 2.0.
# Official: https://t.me/yurii_yurii86 | https://youtube.com/@yurii_yurii86 | https://instagram.com/yurii_yurii86
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_DIR / ".env"
DEFAULT_GUI_ALLOWED_APPS = (
    ["chrome.exe", "explorer.exe", "notepad.exe", "powershell.exe", "Code.exe"]
    if os.name == "nt"
    else ["Google Chrome", "Finder", "Terminal", "Visual Studio Code"]
)

TOKEN_REGEX = re.compile(r"^[A-Za-z0-9._~-]{32,}$")
WEAK_TOKENS = {
    "",
    "change-me",
    "changeme",
    "default",
    "token",
    "secret",
    "password",
    "example",
    "replace-this-with-a-long-random-secret-token",
    "long-random-secret-token-please-use-your-own-value",
}
WEAK_TOKEN_WORDS = ("change", "default", "example", "password", "replace", "secret", "token")


def token_is_safe(token: str) -> bool:
    cleaned = token.strip()
    lowered = cleaned.lower()
    if len(cleaned) < 32:
        return False
    if lowered in WEAK_TOKENS:
        return False
    if len(set(cleaned)) <= 4:
        return False
    if any(word in lowered for word in WEAK_TOKEN_WORDS):
        return False
    return bool(TOKEN_REGEX.fullmatch(cleaned))


def _load_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _json_list(raw: str, default: list[str]) -> list[str]:
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return default
    if not isinstance(value, list):
        return default
    return [str(item) for item in value]


@dataclass
class Settings:
    agent_token: str
    agent_host: str
    agent_port: int
    workspace_roots: list[Path]
    ssh_allowed_hosts: list[str]
    ssh_allowed_cidrs: list[str]
    ssh_known_hosts_path: str
    gui_allowed_apps: list[str]
    enabled_provider_manifests: Path
    state_db_path: Path
    max_output_chars: int
    max_file_bytes: int
    default_timeout_sec: int
    ngrok_domain: str


def load_settings() -> Settings:
    env = _load_env_file()
    env.update(os.environ.copy())

    provider_dir = Path(env.get("ENABLED_PROVIDER_MANIFESTS", str(PROJECT_DIR / "app" / "providers")))
    if not provider_dir.exists():
        provider_dir = PROJECT_DIR / "app" / "providers"

    state_db = Path(env.get("STATE_DB_PATH", str(PROJECT_DIR / "data" / "agent.db")))
    if not state_db.parent.exists():
        state_db = PROJECT_DIR / "data" / "agent.db"

    raw_roots = env.get("WORKSPACE_ROOTS", "")
    workspace_roots = [Path(item.strip()).expanduser().resolve() for item in raw_roots.split(os.pathsep) if item.strip()]
    if not workspace_roots:
        workspace_roots = [PROJECT_DIR]

    return Settings(
        agent_token=env.get("AGENT_TOKEN", "").strip(),
        agent_host=env.get("AGENT_HOST", "127.0.0.1").strip(),
        agent_port=int(env.get("AGENT_PORT", "8787")),
        workspace_roots=workspace_roots,
        ssh_allowed_hosts=_json_list(env.get("SSH_ALLOWED_HOSTS_JSON", "[]"), []),
        ssh_allowed_cidrs=_json_list(env.get("SSH_ALLOWED_CIDRS_JSON", "[]"), []),
        ssh_known_hosts_path=env.get("SSH_KNOWN_HOSTS_PATH", "~/.ssh/known_hosts").strip(),
        gui_allowed_apps=_json_list(env.get("GUI_ALLOWED_APPS_JSON", json.dumps(DEFAULT_GUI_ALLOWED_APPS)), DEFAULT_GUI_ALLOWED_APPS),
        enabled_provider_manifests=provider_dir,
        state_db_path=state_db,
        max_output_chars=int(env.get("MAX_OUTPUT_CHARS", "50000")),
        max_file_bytes=int(env.get("MAX_FILE_BYTES", "1048576")),
        default_timeout_sec=int(env.get("DEFAULT_TIMEOUT_SEC", "30")),
        ngrok_domain=env.get("NGROK_DOMAIN", "").strip(),
    )


def validate_runtime_settings(settings: Settings) -> None:
    if not token_is_safe(settings.agent_token):
        raise RuntimeError(
            "AGENT_TOKEN не заполнен или выглядит небезопасно.\n"
            "Откройте файл .env, найдите строку AGENT_TOKEN=... и вставьте длинный случайный токен."
        )
