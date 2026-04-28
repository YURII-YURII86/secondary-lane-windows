# Second Lane
# Copyright (c) 2026 Yurii Slepnev
# Licensed under the Apache License, Version 2.0.
# Official: https://t.me/yurii_yurii86 | https://youtube.com/@yurii_yurii86 | https://instagram.com/yurii_yurii86
# /// CONTEXT_BLOCK
# ID: second_lane_control_panel
# TYPE: interface
# PURPOSE: Local operator panel for starting, stopping, and observing the daemon and public tunnel.
# DEPENDS_ON: [.env, openapi.gpts.yaml, .venv]
# USED_BY: [Запустить GPTS Agent.command, Запустить GPTS Agent.bat]
# STATE: active
# /// ---
from __future__ import annotations

import os
import re
import shutil
import signal
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
import json
import sys
from dataclasses import dataclass
from pathlib import Path
import datetime
import platform as _platform
import tkinter as tk
from tkinter import BOTH, END, LEFT, Button, Frame, Label, StringVar, Text, Tk

from app.core.config import token_is_safe

try:
    import yaml as _yaml  # pyyaml — installed into .venv; may be absent on first launch
except ImportError:
    _yaml = None  # type: ignore[assignment]  # update_openapi_url falls back to regex

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency at runtime
    certifi = None


# ---------------------------------------------------------------------------
# UI design tokens — Catppuccin Mocha palette
# ---------------------------------------------------------------------------
_C: dict[str, str] = {
    "base":     "#1e1e2e", "mantle":   "#181825", "crust":    "#11111b",
    "surface0": "#313244", "surface1": "#45475a", "surface2": "#585b70",
    "overlay0": "#6c7086", "overlay1": "#7f849c",
    "text":     "#cdd6f4", "subtext1": "#bac2de", "subtext0": "#a6adc8",
    "green":    "#a6e3a1", "teal":     "#94e2d5", "blue":     "#89b4fa",
    "mauve":    "#cba6f7", "lavender": "#b4befe", "yellow":   "#f9e2af",
    "peach":    "#fab387", "red":      "#f38ba8", "maroon":   "#eba0ac",
}
_SYS       = _platform.system()
_FONT_UI   = "Helvetica Neue" if _SYS == "Darwin" else ("Segoe UI"  if _SYS == "Windows" else "Sans")
_FONT_MONO = "Menlo"          if _SYS == "Darwin" else ("Consolas"  if _SYS == "Windows" else "Monospace")


PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
OPENAPI_FILES = [
    PROJECT_DIR / "openapi.gpts.yaml",
]
IS_WINDOWS = os.name == "nt"
VENV_DIR = PROJECT_DIR / ".venv"
VENV_UVICORN = VENV_DIR / ("Scripts/uvicorn.exe" if IS_WINDOWS else "bin/uvicorn")
LOCAL_URL = "http://127.0.0.1:8787"
# Default is just the project folder itself — do not add C:\Projects or
# D:\Workspace which do not exist on most machines and confused users
# into thinking they had to create those folders.
DEFAULT_WORKSPACE_ROOTS = str(PROJECT_DIR)

# --- Tunnel defaults ---
DEFAULT_NGROK_DOMAIN = "your-domain.ngrok-free.dev"
TUNNEL_HEALTH_ATTEMPTS = 4
TUNNEL_HEALTH_DELAY_SEC = 2.0
TUNNEL_HEALTH_TIMEOUT_SEC = 6
TUNNEL_RESTART_COOLDOWN_SEC = 5
TUNNEL_MONITOR_INTERVAL_MS = 10_000
NGROK_BLOCKED_IP_ERROR = "ERR_NGROK_9040"
PUBLIC_CHECK_INTERVAL_SEC = 25
PUBLIC_CHECK_MAX_FAILURES = 2
RECOVERY_BACKOFF_STEPS_SEC = [3, 10, 30]


@dataclass
class TunnelFailure:
    code: str
    summary: str
    recoverable: bool


@dataclass
class LocalDaemonProcess:
    pid: int
    cwd: Path | None
    command: str
    owned_by_current_project: bool = False


class ControlPanel:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Second Lane Control")

        self.agent_proc: subprocess.Popen | None = None
        self.tunnel_proc: subprocess.Popen | None = None
        self._using_external_daemon = False
        self.tunnel_url = StringVar(value="Туннель: не запущен")
        self.agent_status = StringVar(value="Демон: не запущен")
        self.last_url: str | None = None
        self._tunnel_restart_count = 0
        self._tunnel_max_restarts = 5
        self._tunnel_blocked_reason: str | None = None
        self._last_tunnel_failure: TunnelFailure | None = None
        self._recovering_tunnel = False
        self._public_check_running = False
        self._last_public_check_ts = 0.0
        self._public_check_failures = 0

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_status()

    # --- UI ---

    def _build_ui(self) -> None:
        # ── Window ──────────────────────────────────────────────────────
        self.root.configure(bg=_C["base"])
        self.root.geometry("940x660")
        self.root.minsize(800, 540)

        # ── Header bar ──────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=_C["mantle"], height=54)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="● Second Lane Control",
            font=(_FONT_UI, 16, "bold"),
            bg=_C["mantle"], fg=_C["mauve"],
        ).pack(side=tk.LEFT, padx=20, pady=14)
        tk.Label(
            hdr,
            text="by Yurii Slepnev",
            font=(_FONT_UI, 10),
            bg=_C["mantle"], fg=_C["overlay1"],
        ).pack(side=tk.RIGHT, padx=20)

        # ── Status section ───────────────────────────────────────────────
        sx = tk.Frame(self.root, bg=_C["base"])
        sx.pack(fill=tk.X, padx=14, pady=(10, 0))

        # Daemon row
        dr = tk.Frame(sx, bg=_C["surface0"], padx=14, pady=9)
        dr.pack(fill=tk.X, pady=(0, 3))
        self._daemon_dot = tk.Label(
            dr, text="●", font=(_FONT_UI, 15),
            bg=_C["surface0"], fg=_C["overlay0"],
        )
        self._daemon_dot.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(
            dr, text="ДЕМОН", font=(_FONT_UI, 8, "bold"),
            bg=_C["surface0"], fg=_C["overlay1"], width=8, anchor="w",
        ).pack(side=tk.LEFT)
        tk.Label(
            dr, textvariable=self.agent_status, font=(_FONT_UI, 11),
            bg=_C["surface0"], fg=_C["subtext1"], anchor="w", wraplength=620,
        ).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # Tunnel row
        tr = tk.Frame(sx, bg=_C["surface0"], padx=14, pady=9)
        tr.pack(fill=tk.X)
        self._tunnel_dot = tk.Label(
            tr, text="●", font=(_FONT_UI, 15),
            bg=_C["surface0"], fg=_C["overlay0"],
        )
        self._tunnel_dot.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(
            tr, text="ТУННЕЛЬ", font=(_FONT_UI, 8, "bold"),
            bg=_C["surface0"], fg=_C["overlay1"], width=8, anchor="w",
        ).pack(side=tk.LEFT)
        # Pack copy button on the RIGHT before the URL label so it stays right-aligned
        tk.Button(
            tr, text="Скопировать URL", font=(_FONT_UI, 9),
            bg=_C["surface1"], fg=_C["subtext0"],
            activebackground=_C["surface2"], activeforeground=_C["text"],
            relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
            command=self.copy_url,
        ).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Label(
            tr, textvariable=self.tunnel_url, font=(_FONT_UI, 11),
            bg=_C["surface0"], fg=_C["teal"], anchor="w", wraplength=500,
        ).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # Colour traces for status indicator dots
        self.agent_status.trace_add("write", self._update_daemon_dot)
        self.tunnel_url.trace_add("write", self._update_tunnel_dot)

        # ── Action buttons ────────────────────────────────────────────────
        btn = tk.Frame(self.root, bg=_C["base"])
        btn.pack(fill=tk.X, padx=14, pady=10)
        _p = dict(
            font=(_FONT_UI, 12, "bold"),
            bg=_C["mauve"], fg=_C["crust"],
            activebackground=_C["lavender"], activeforeground=_C["crust"],
            relief="flat", bd=0, padx=22, pady=10, cursor="hand2",
        )
        _s = dict(
            font=(_FONT_UI, 11),
            bg=_C["surface0"], fg=_C["text"],
            activebackground=_C["surface1"], activeforeground=_C["text"],
            relief="flat", bd=0, padx=18, pady=10, cursor="hand2",
        )
        _d = dict(
            font=(_FONT_UI, 11),
            bg=_C["surface0"], fg=_C["red"],
            activebackground=_C["surface1"], activeforeground=_C["maroon"],
            relief="flat", bd=0, padx=18, pady=10, cursor="hand2",
        )
        tk.Button(btn, text="▶  Запустить",     **_p, command=self.start_all).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn, text="↺  Перезапустить", **_s, command=self.restart_daemon).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn, text="■  Выключить",      **_d, command=self.stop_all).pack(side=tk.LEFT, padx=(0, 28))
        tk.Button(btn, text="✓  Проверить",      **_s, command=self.check_now).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn, text="⚙  Открыть .env",  **_s, command=self.open_env_file).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn, text="Файлы GPT",         **_s, command=self.open_project_folder).pack(side=tk.LEFT)

        # ── Log console ───────────────────────────────────────────────────
        lhdr = tk.Frame(self.root, bg=_C["mantle"])
        lhdr.pack(fill=tk.X, padx=14)
        tk.Label(
            lhdr, text="ЖУРНАЛ СОБЫТИЙ", font=(_FONT_UI, 8, "bold"),
            bg=_C["mantle"], fg=_C["overlay0"], padx=12, pady=5,
        ).pack(side=tk.LEFT)
        tk.Button(
            lhdr, text="Очистить", font=(_FONT_UI, 8),
            bg=_C["mantle"], fg=_C["overlay1"],
            activebackground=_C["surface0"], activeforeground=_C["text"],
            relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
            command=lambda: self.log.delete("1.0", END),
        ).pack(side=tk.RIGHT, padx=4)

        lbox = tk.Frame(self.root, bg=_C["crust"])
        lbox.pack(fill=BOTH, expand=True, padx=14, pady=(0, 14))
        vsb = tk.Scrollbar(lbox, bg=_C["surface0"], troughcolor=_C["crust"],
                           activebackground=_C["surface1"])
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log = Text(
            lbox,
            wrap="word",
            bg=_C["crust"], fg=_C["text"],
            font=(_FONT_MONO, 11),
            insertbackground=_C["text"],
            selectbackground=_C["surface1"],
            selectforeground=_C["text"],
            relief="flat", bd=0,
            padx=14, pady=8,
            yscrollcommand=vsb.set,
        )
        self.log.pack(side=tk.LEFT, fill=BOTH, expand=True)
        vsb.config(command=self.log.yview)

        # Log colour tags
        self.log.tag_config("ts",     foreground=_C["overlay0"])
        self.log.tag_config("info",   foreground=_C["subtext0"])
        self.log.tag_config("ok",     foreground=_C["green"])
        self.log.tag_config("warn",   foreground=_C["peach"])
        self.log.tag_config("error",  foreground=_C["red"])
        self.log.tag_config("ngrok",  foreground=_C["blue"])
        self.log.tag_config("agent",  foreground=_C["mauve"])
        self.log.tag_config("action", foreground=_C["yellow"])
        self.log.tag_config("url",    foreground=_C["teal"])
        self.log.tag_config("dim",    foreground=_C["overlay0"])
        self.log.tag_config("hdr",    foreground=_C["mauve"],
                            font=(_FONT_MONO, 12, "bold"))
        self._write_log_header()

    def write_log(self, text: str) -> None:
        if not text:
            return
        now = datetime.datetime.now().strftime("%H:%M:%S")
        for line in text.rstrip("\n").split("\n"):
            self.log.insert(END, f"{now}  ", "ts")
            self.log.insert(END, line + "\n", self._log_tag(line))
        self.log.see(END)

    def _write_log_header(self) -> None:
        self.log.insert(END, "\n  Second Lane by Yurii Slepnev\n", "hdr")
        sep = "  " + "─" * 46 + "\n"
        self.log.insert(END, sep, "dim")
        for lbl, url in (
            ("  Telegram: ", "https://t.me/yurii_yurii86"),
            ("  YouTube:  ", "https://youtube.com/@yurii_yurii86"),
            ("  Instagram:", "https://instagram.com/yurii_yurii86"),
        ):
            self.log.insert(END, lbl, "dim")
            self.log.insert(END, url + "\n", "url")
        self.log.insert(END, "  Licensed under Apache-2.0\n", "dim")
        self.log.insert(END, sep, "dim")
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.insert(END, f"\n{now}  ", "ts")
        self.log.insert(END, "Панель готова — нажми «Запустить».\n", "info")
        self.log.see(END)

    def _log_tag(self, line: str) -> str:
        low = line.lower()
        if line.startswith("[ngrok]"):
            return "ngrok"
        if line.startswith("[agent]"):
            return "agent"
        if any(k in low for k in (
            "ok ✓", "туннель активен", "url вставлен", "готов",
            "скопировал", "автопроверка туннеля: ok", "снова отвечает",
            "работает", "уже запущен", "активен",
        )):
            return "ok"
        if any(k in low for k in (
            "ошибка", "упал", "не смог", "заблокировал", "err_ngrok",
            "не найден", "не поднялся", "неизвестн", "невалид",
        )):
            return "error"
        if any(k in low for k in (
            "восстановление", "попыт", "проверка публичного", "предупрежд",
        )):
            return "warn"
        if any(k in low for k in (
            "запускаю", "поднимаю", "останавливаю", "перезапуск", "создаю",
        )):
            return "action"
        if "https://" in line or "http://" in line:
            return "url"
        return "info"

    def _update_daemon_dot(self, *_: object) -> None:
        val = self.agent_status.get().lower()
        if "работает" in val or "уже запущен" in val:
            color = _C["green"]
        elif "перезапуск" in val:
            color = _C["peach"]
        else:
            color = _C["overlay0"]
        try:
            self._daemon_dot.configure(fg=color)
        except Exception:
            pass

    def _update_tunnel_dot(self, *_: object) -> None:
        val = self.tunnel_url.get().lower()
        if "https://" in val:
            color = _C["green"]
        elif "восстановление" in val:
            color = _C["peach"]
        elif any(k in val for k in ("ошибка", "упал", "заблокировал")):
            color = _C["red"]
        else:
            color = _C["overlay0"]
        try:
            self._tunnel_dot.configure(fg=color)
        except Exception:
            pass

    # --- Env / config ---

    def load_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if ENV_FILE.exists():
            # utf-8-sig strips BOM so the first key is never corrupted on Windows
            for line in ENV_FILE.read_text("utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
        env["ENABLED_PROVIDER_MANIFESTS"] = str(PROJECT_DIR / "app" / "providers")
        env["STATE_DB_PATH"] = str(PROJECT_DIR / "data" / "agent.db")
        env["AGENT_HOST"] = "127.0.0.1"
        env["AGENT_PORT"] = "8787"
        env.setdefault("WORKSPACE_ROOTS", DEFAULT_WORKSPACE_ROOTS)
        return env

    def agent_token(self) -> str:
        return self.load_env().get("AGENT_TOKEN", "")

    def agent_token_is_safe(self) -> bool:
        return token_is_safe(self.agent_token())

    def explain_unsafe_token(self) -> None:
        self.write_log(
            "Не могу безопасно запустить агента: токен защиты не заполнен или выглядит как временная заглушка.\n\n"
            "Что это значит простыми словами:\n"
            "- этот токен работает как секретный ключ для доступа к агенту через интернет;\n"
            "- если оставить пустое значение или что-то вроде change-me, защиту легко угадать;\n"
            "- поэтому запуск сейчас специально остановлен.\n\n"
            "Что сделать:\n"
            f"1. Открой файл {ENV_FILE}\n"
            "2. Найди строку AGENT_TOKEN=...\n"
            "3. Вставь после = длинный случайный набор символов\n"
            "4. Сохрани файл\n"
            "5. Снова нажми «Запустить»\n\n"
            "Самый простой способ создать хороший токен:\n"
            "py -3.13 -c \"import secrets; print(secrets.token_urlsafe(48))\"\n\n"
            "Важно:\n"
            "- не используй change-me, default, token, secret, password или примеры из инструкции;\n"
            "- не публикуй этот токен в скриншотах и сообщениях.\n"
        )

    def ngrok_domain(self) -> str:
        return self.load_env().get("NGROK_DOMAIN", DEFAULT_NGROK_DOMAIN)

    def _classify_ngrok_output(self, text: str) -> TunnelFailure:
        lowered = text.lower()
        if NGROK_BLOCKED_IP_ERROR.lower() in lowered:
            return TunnelFailure(
                code="ip_blocked",
                summary="ngrok заблокировал запуск с текущего IP",
                recoverable=False,
            )
        if "authentication failed" in lowered or "invalid authtoken" in lowered:
            return TunnelFailure(
                code="auth_failed",
                summary="ngrok отклонил токен или доступ аккаунта",
                recoverable=False,
            )
        if "reserved domain" in lowered or "domain" in lowered and ("invalid" in lowered or "not found" in lowered):
            return TunnelFailure(
                code="domain_invalid",
                summary="ngrok не принял указанный домен",
                recoverable=False,
            )
        if "address already in use" in lowered:
            return TunnelFailure(
                code="port_busy",
                summary="порт 8787 уже занят",
                recoverable=True,
            )
        if "timeout" in lowered or "eof" in lowered or "failed to reconnect session" in lowered:
            return TunnelFailure(
                code="network_temporary",
                summary="временная проблема сети или сессии ngrok",
                recoverable=True,
            )
        return TunnelFailure(
            code="process_crashed",
            summary="ngrok завершился до готовности туннеля",
            recoverable=True,
        )

    def _describe_tunnel_failure(self, failure: TunnelFailure) -> str:
        if failure.code == "ip_blocked":
            return (
                "ngrok не пустил этот IP. "
                "Это внешняя блокировка со стороны ngrok, сервис сам её не снимет."
            )
        if failure.code == "auth_failed":
            return "ngrok не принял токен или права аккаунта."
        if failure.code == "domain_invalid":
            return "ngrok не смог использовать домен из .env."
        if failure.code == "port_busy":
            return "локальный порт 8787 занят другим процессом."
        if failure.code == "network_temporary":
            return "временный сетевой сбой при подключении к ngrok."
        return failure.summary

    def _find_ngrok(self) -> str | None:
        """Return full path to ngrok, checking PATH and common install locations."""
        configured_path = self.load_env().get("NGROK_PATH", "").strip().strip("'\"")
        if configured_path:
            candidate = Path(configured_path).expanduser()
            try:
                if candidate.is_file() and candidate.name.lower() == "ngrok.exe":
                    return str(candidate)
            except OSError:
                pass
        found = shutil.which("ngrok")
        if found:
            return found
        if IS_WINDOWS:
            # WinGet installs to AppData\Local\Microsoft\WinGet\Links — not always in PATH
            # of child processes spawned from Explorer. Check explicitly.
            _lad = os.environ.get("LOCALAPPDATA", "")
            _pf  = os.environ.get("ProgramFiles", r"C:\Program Files")
            _up  = os.environ.get("USERPROFILE", "")
            candidates = [
                Path(_lad) / "Microsoft" / "WinGet" / "Links" / "ngrok.exe",
                Path(_lad) / "ngrok" / "ngrok.exe",
                Path(_pf)  / "ngrok" / "ngrok.exe",
                Path(_up)  / "scoop" / "apps" / "ngrok" / "current" / "ngrok.exe",
                Path(r"C:\ProgramData\chocolatey\bin\ngrok.exe"),
                Path(_up) / "Downloads" / "ngrok.exe",
            ]
            for c in candidates:
                try:
                    if c.exists():
                        self.write_log(f"ngrok найден вне PATH: {c}\n")
                        return str(c)
                except Exception:
                    pass
            for root in (
                Path(_lad) / "Microsoft" / "WinGet" / "Packages",
                Path(_pf) / "WinGet" / "Packages",
            ):
                try:
                    if not root.exists():
                        continue
                    for c in root.glob("**/ngrok.exe"):
                        if c.is_file():
                            self.write_log(f"ngrok найден поиском: {c}\n")
                            return str(c)
                except Exception:
                    pass
            downloads = Path(_up) / "Downloads"
            try:
                if downloads.exists():
                    for c in downloads.glob("ngrok*/ngrok.exe"):
                        if c.is_file():
                            self.write_log(f"ngrok найден поиском: {c}\n")
                            return str(c)
            except Exception:
                pass
        return None

    def _preflight_tunnel_check(self) -> tuple[bool, str]:
        ngrok_path = self._find_ngrok()
        if not ngrok_path:
            install_hint = (
                "ngrok не найден. Открой установщик: он попробует поставить ngrok автоматически или даст выбрать ngrok.exe"
                if IS_WINDOWS
                else "ngrok не найден. Установи: brew install ngrok"
            )
            return False, install_hint
        domain = self.ngrok_domain().strip()
        if not domain:
            return False, "в .env не задан NGROK_DOMAIN"
        try:
            result = subprocess.run(
                [ngrok_path, "config", "check"],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            return False, f"не смог проверить конфиг ngrok: {exc}"
        if result.returncode != 0:
            output = (result.stdout or "").strip()
            return False, f"конфиг ngrok невалиден: {output or 'неизвестная ошибка'}"
        if not self._local_daemon_ready():
            return False, "локальный демон не отвечает на /health"
        return True, "OK"

    # --- Python env ---

    def _python_candidates(self) -> list[list[str]]:
        candidates: list[list[str]] = []
        if sys.executable:
            candidates.append([sys.executable])
        if IS_WINDOWS:
            candidates.extend([["py", "-3.13"], ["python"]])
        else:
            candidates.extend([["python3.13"], ["python3"]])
        unique: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for item in candidates:
            key = tuple(item)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _resolve_python_command(self) -> list[str] | None:
        for command in self._python_candidates():
            try:
                result = subprocess.run(
                    [*command, "--version"],
                    cwd=PROJECT_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0 and "3.13" in (result.stdout or ""):
                return command
        return None

    def ensure_uvicorn(self) -> bool:
        if VENV_UVICORN.exists():
            return True
        python_cmd = self._resolve_python_command()
        if python_cmd is None:
            self.write_log(
                "Не нашёл рабочий Python 3.13. Локальный запуск и pytest в этом проекте сейчас подтверждены именно на Python 3.13; "
                "Python 3.14 для этого pinned stack не считается поддержанным.\n"
            )
            return False
        self.write_log(f"Не нашёл готовый uvicorn. Создаю окружение через {' '.join(python_cmd)}...\n")
        pip_bin = str(VENV_DIR / ("Scripts/pip.exe" if IS_WINDOWS else "bin/pip"))
        try:
            venv_result = subprocess.run(
                [*python_cmd, "-m", "venv", str(VENV_DIR)],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=120,
            )
            if venv_result.returncode != 0:
                self.write_log(
                    f"Не смог создать виртуальное окружение ({' '.join(python_cmd)} -m venv).\n"
                    f"Код возврата: {venv_result.returncode}\n"
                    f"Вывод: {(venv_result.stdout or '').strip()[:800]}\n"
                    f"Проверь: 1) Python установлен полностью (не только embeddable); "
                    f"2) есть права записи в {VENV_DIR}; 3) антивирус не блокирует создание файлов.\n"
                )
                return False
            self.write_log("Виртуальное окружение создано. Устанавливаю зависимости...\n")
            # Live-stream pip output into the log panel (Popen + _stream_process)
            # — in pythonw.exe the GUI has no console, so capturing is required.
            pip_proc = subprocess.Popen(
                [pip_bin, "install", "--quiet", "-r", str(PROJECT_DIR / "requirements.txt")],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
            )
            threading.Thread(target=self._stream_process, args=(pip_proc, "pip"), daemon=True).start()
            pip_proc.wait()
            if pip_proc.returncode != 0:
                self.write_log(
                    f"pip install завершился с кодом {pip_proc.returncode}. См. строки [pip] выше.\n"
                    f"Типичные причины: нет интернета, корпоративный прокси, блокировка SSL, "
                    f"устаревший pip (запусти '{pip_bin} install --upgrade pip').\n"
                )
                return False
            self.write_log("Зависимости установлены.\n")
            return True
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.write_log(
                f"Не смог подготовить Python-окружение через {' '.join(python_cmd)}: {exc}\n"
                f"Проверь сетевое соединение и что Python не запущен от другого пользователя.\n"
            )
            return False

    # --- Start / stop ---

    def start_all(self) -> None:
        self._tunnel_restart_count = 0
        self._last_tunnel_failure = None
        threading.Thread(target=self._start_all_worker, daemon=True).start()

    def restart_daemon(self) -> None:
        self._tunnel_restart_count = 0
        self._last_tunnel_failure = None
        threading.Thread(target=self._restart_daemon_worker, daemon=True).start()

    def _local_daemon_ready(self) -> bool:
        ok, _ = self._url_ok(f"{LOCAL_URL}/health")
        return ok

    def _stream_process(self, proc: subprocess.Popen, label: str) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            short = line.rstrip()
            if short:
                self.write_log(f"[{label}] {short}\n")
        exit_code = proc.poll()
        if exit_code not in (None, 0):
            self.write_log(f"[{label}] процесс завершился с кодом {exit_code}\n")

    def _command_line_belongs_to_current_project(self, command: str) -> bool:
        if not command:
            return False
        normalized = command.replace("/", "\\").lower()
        project_markers = [
            str(PROJECT_DIR).replace("/", "\\").lower(),
            str(VENV_UVICORN).replace("/", "\\").lower(),
            str((PROJECT_DIR / "gpts_agent_control.py")).replace("/", "\\").lower(),
        ]
        return any(marker and marker in normalized for marker in project_markers)

    def _find_listener_pid(self, port: int) -> int | None:
        if IS_WINDOWS:
            try:
                result = subprocess.run(
                    ["netstat", "-ano", "-p", "tcp"],
                    cwd=PROJECT_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=8,
                )
            except Exception:
                return None
            pattern = re.compile(rf"^\s*TCP\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$", re.IGNORECASE)
            for line in (result.stdout or "").splitlines():
                match = pattern.match(line)
                if match:
                    try:
                        return int(match.group(1))
                    except ValueError:
                        return None
            return None
        try:
            result = subprocess.run(
                ["lsof", "-tiTCP:%s" % port, "-sTCP:LISTEN"],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
        except Exception:
            return None
        raw = (result.stdout or "").strip().splitlines()
        if not raw:
            return None
        try:
            return int(raw[0].strip())
        except ValueError:
            return None

    def _describe_local_daemon_process(self) -> LocalDaemonProcess | None:
        pid = self._find_listener_pid(8787)
        if pid is None:
            return None
        cwd: Path | None = None
        command = ""
        if IS_WINDOWS:
            try:
                cmd_result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        f"(Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\").CommandLine",
                    ],
                    cwd=PROJECT_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=8,
                )
                command = (cmd_result.stdout or "").strip()
            except Exception:
                command = ""
            owned = self._command_line_belongs_to_current_project(command)
            return LocalDaemonProcess(pid=pid, cwd=None, command=command, owned_by_current_project=owned)
        try:
            cwd_result = subprocess.run(
                ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            for line in (cwd_result.stdout or "").splitlines():
                if line.startswith("n"):
                    cwd = Path(line[1:]).resolve()
                    break
        except Exception:
            cwd = None
        try:
            cmd_result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            command = (cmd_result.stdout or "").strip()
        except Exception:
            command = ""
        return LocalDaemonProcess(pid=pid, cwd=cwd, command=command)

    def _current_project_owns_port_8787(self) -> bool:
        info = self._describe_local_daemon_process()
        if info is None:
            return False
        if IS_WINDOWS and info.cwd is None:
            return info.owned_by_current_project
        if info.cwd is None:
            return False
        return info.cwd == PROJECT_DIR

    def _wait_for_port_8787_to_clear(self, attempts: int = 10, delay_sec: float = 0.5) -> bool:
        for _ in range(attempts):
            time.sleep(delay_sec)
            if self._find_listener_pid(8787) is None:
                return True
        return self._find_listener_pid(8787) is None

    def _stop_pid(self, pid: int, label: str) -> bool:
        if IS_WINDOWS:
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T"],
                    cwd=PROJECT_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=10,
                )
            except Exception as exc:
                self.write_log(f"Не смог остановить {label} PID {pid} через taskkill: {exc}\n")
                return False
            if result.returncode == 0:
                return True
            try:
                forced = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    cwd=PROJECT_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=10,
                )
            except Exception as exc:
                self.write_log(f"Не смог принудительно остановить {label} PID {pid}: {exc}\n")
                return False
            if forced.returncode == 0:
                return True
            self.write_log(f"taskkill не смог остановить {label} PID {pid}: {(forced.stdout or result.stdout or '').strip()}\n")
            return False
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            return True
        except Exception as exc:
            self.write_log(f"Не смог остановить {label} PID {pid}: {exc}\n")
            return False
        return True

    def _stop_foreign_daemon_on_8787(self) -> bool:
        info = self._describe_local_daemon_process()
        if info is None:
            return False
        if IS_WINDOWS and info.cwd is None and not info.owned_by_current_project:
            self.write_log(
                "На Windows не смог надёжно определить владельца порта 8787.\n"
                "Если там старый чужой демон, останови его вручную и нажми «Запустить» ещё раз.\n"
            )
            return False
        if info.cwd == PROJECT_DIR:
            return False
        self.write_log(
            "На порту 8787 найден чужой демон от другого проекта.\n"
            f"PID: {info.pid}\n"
            f"CWD: {info.cwd or 'не удалось определить'}\n"
            "Останавливаю его, чтобы поднять текущий проект.\n"
        )
        if not self._stop_pid(info.pid, "чужой демон"):
            return False
        if self._wait_for_port_8787_to_clear():
            return True
        try:
            os.kill(info.pid, signal.SIGTERM)
        except Exception:
            pass
        time.sleep(1.0)
        return self._find_listener_pid(8787) is None

    def _stop_current_project_daemon_on_8787(self) -> bool:
        info = self._describe_local_daemon_process()
        if info is None:
            self.write_log("На порту 8787 нет живого демона текущего проекта.\n")
            return True
        if IS_WINDOWS and info.cwd is None and not info.owned_by_current_project:
            self.write_log(
                "На Windows не смог надёжно определить, чей процесс сидит на порту 8787.\n"
                "Если нужен жёсткий рестарт, сначала останови старый процесс вручную.\n"
            )
            return False
        if info.cwd != PROJECT_DIR:
            self.write_log(
                "На порту 8787 сейчас не текущий проект, а другой процесс.\n"
                "Для жёсткого рестарта этого проекта сначала освобожу порт обычным сценарием запуска.\n"
            )
            return self._stop_foreign_daemon_on_8787()
        self.write_log(
            "Перезапускаю текущий демон проекта на порту 8787.\n"
            f"PID: {info.pid}\n"
        )
        if not self._stop_pid(info.pid, "текущий демон"):
            return False
        if self._wait_for_port_8787_to_clear():
            return True
        try:
            os.kill(info.pid, signal.SIGTERM)
        except Exception:
            pass
        time.sleep(1.0)
        return self._find_listener_pid(8787) is None

    def _restart_daemon_worker(self) -> None:
        if not self.agent_token_is_safe():
            self.explain_unsafe_token()
            return
        self._tunnel_restart_count = self._tunnel_max_restarts
        self._stop_process(self.tunnel_proc, "туннель")
        self.tunnel_proc = None
        self.last_url = None
        self._tunnel_blocked_reason = None
        self._last_tunnel_failure = None
        self._recovering_tunnel = False
        self._public_check_failures = 0
        self.tunnel_url.set("Туннель: не запущен")
        if self.agent_proc is not None and self.agent_proc.poll() is None:
            self._stop_process(self.agent_proc, "демон")
            self.agent_proc = None
        if not self._stop_current_project_daemon_on_8787():
            self.write_log("Не смог освободить порт 8787 для жёсткого рестарта демона.\n")
            return
        self._using_external_daemon = False
        self.agent_status.set("Демон: перезапуск...")
        self.write_log("Поднимаю новый процесс демона для текущего проекта...\n")
        self._tunnel_restart_count = 0
        self._last_tunnel_failure = None
        self._start_all_worker()

    def _start_all_worker(self) -> None:
        # --- Daemon ---
        if self.agent_proc and self.agent_proc.poll() is None:
            self.write_log("Демон уже запущен.\n")
        elif not self.agent_token_is_safe():
            self.explain_unsafe_token()
            return
        elif self._local_daemon_ready() and not self._current_project_owns_port_8787():
            if IS_WINDOWS:
                self.write_log(
                    "На 127.0.0.1:8787 уже отвечает живой процесс, но панель не подтвердила, "
                    "что это именно текущий проект.\n"
                    "Из соображений безопасности не запускаю туннель к неподтверждённому сервису.\n"
                    "Что сделать: освободи порт 8787 или перезапусти демон текущего проекта, "
                    "а потом снова нажми «Запустить».\n"
                )
                self.agent_status.set("Демон: порт 8787 занят неподтверждённым процессом")
                return
            elif not self._stop_foreign_daemon_on_8787():
                self.write_log(
                    "Не смог освободить порт 8787 от старого проекта.\n"
                    "Закрой старый демон вручную и нажми «Запустить» ещё раз.\n"
                )
                return
        elif self._local_daemon_ready():
            self._using_external_daemon = True
            self.write_log("На 127.0.0.1:8787 уже отвечает живой демон. Использую его и не запускаю второй экземпляр.\n")
        else:
            if not self.ensure_uvicorn():
                return
            env = self.load_env()
            self._using_external_daemon = False
            self.write_log("Запускаю демона на http://127.0.0.1:8787 ...\n")
            self.agent_proc = subprocess.Popen(
                [str(VENV_UVICORN), "app.main:app", "--host", "127.0.0.1", "--port", "8787"],
                cwd=PROJECT_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            threading.Thread(target=self._stream_process, args=(self.agent_proc, "agent"), daemon=True).start()
            time.sleep(1.5)
            if self.agent_proc.poll() is not None and self._local_daemon_ready():
                self.agent_proc = None
                self._using_external_daemon = True
                self.write_log("Новый процесс демона не закрепился, но локальный health уже отвечает. Продолжаю с существующим демоном.\n")

        # --- Tunnel ---
        self._start_tunnel()

    def _start_tunnel(self) -> None:
        if self.tunnel_proc and self.tunnel_proc.poll() is None:
            self.write_log("Туннель уже запущен.\n")
            return

        ok, detail = self._preflight_tunnel_check()
        if not ok:
            self.write_log(f"Не запускаю туннель: {detail}\n")
            return

        domain = self.ngrok_domain()
        public_url = f"https://{domain}"
        self._tunnel_blocked_reason = None
        self._last_tunnel_failure = None
        self.write_log(f"Запускаю ngrok туннель → {public_url} ...\n")

        ngrok_cmd = self._find_ngrok() or "ngrok"
        self.tunnel_proc = subprocess.Popen(
            [ngrok_cmd, "http", "8787", f"--url={domain}", "--log=stdout", "--log-format=logfmt"],
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._stream_ngrok, args=(self.tunnel_proc,), daemon=True).start()

    def _stream_ngrok(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        tunnel_ready = False
        captured_lines: list[str] = []
        for line in proc.stdout:
            captured_lines.append(line)
            if len(captured_lines) > 40:
                captured_lines.pop(0)
            # Show important lines in log, skip noisy ones
            if any(k in line for k in ("msg=", "err=", "lvl=warn", "lvl=err")):
                short = line.strip()
                if len(short) > 200:
                    short = short[:200] + "..."
                self.write_log(f"[ngrok] {short}\n")

            if NGROK_BLOCKED_IP_ERROR in line:
                self._last_tunnel_failure = self._classify_ngrok_output(line)
                self._tunnel_blocked_reason = self._describe_tunnel_failure(self._last_tunnel_failure)
                self.tunnel_url.set("Туннель: ngrok заблокировал IP")
                self.write_log(
                    "ngrok не пустил агент с текущего IP (ERR_NGROK_9040).\n"
                    "Простыми словами: токен и проект в порядке, но сам сервис ngrok "
                    "не разрешает подключение из этой сети/IP.\n"
                    "Что поможет: другая сеть, другой внешний IP, VPN/VPS вне заблокированного диапазона.\n"
                )

            # Detect tunnel is up
            if "started tunnel" in line or "url=https://" in line:
                domain = self.ngrok_domain()
                self.last_url = f"https://{domain}"
                self.tunnel_url.set(f"Туннель: {self.last_url}")
                self.update_openapi_url(self.last_url)
                self.write_log(f"Туннель активен: {self.last_url}\n")
                self.write_log("URL вставлен в openapi.gpts.yaml\n")
                tunnel_ready = True
                threading.Thread(target=self._validate_tunnel_after_start, daemon=True).start()

        # Process exited — tunnel is dead
        exit_code = proc.poll()
        if self._tunnel_blocked_reason:
            self.last_url = None
            return
        if not tunnel_ready:
            failure_text = "".join(captured_lines)
            self._last_tunnel_failure = self._classify_ngrok_output(failure_text)
            detail = self._describe_tunnel_failure(self._last_tunnel_failure)
            self.last_url = None
            self.tunnel_url.set("Туннель: ошибка запуска")
            self.write_log(f"Туннель не поднялся: {detail}\n")
            self._schedule_tunnel_recovery(self._last_tunnel_failure)
            return
        if tunnel_ready or self.last_url:
            self.write_log(f"ngrok завершился (exit code: {exit_code})\n")
            self.last_url = None
            self.tunnel_url.set("Туннель: упал")
            self._last_tunnel_failure = TunnelFailure(
                code="process_crashed",
                summary=f"ngrok завершился с кодом {exit_code}",
                recoverable=True,
            )
            self._schedule_tunnel_recovery(self._last_tunnel_failure)

    def _validate_tunnel_after_start(self) -> None:
        if not self.last_url:
            return
        tunnel_ok, detail = self._check_public_gpts_ready()
        self.write_log(f"Автопроверка туннеля: {'OK ✓' if tunnel_ok else detail}\n")
        if not tunnel_ok:
            self.write_log(f"Туннель поднялся, но проверка не прошла: {detail}\n")

    def update_openapi_url(self, url: str) -> None:
        for openapi_file in OPENAPI_FILES:
            if not openapi_file.exists():
                continue
            text = openapi_file.read_text("utf-8")
            updated_text = None
            try:
                payload = _yaml.safe_load(text) or {} if _yaml is not None else None
            except Exception:
                payload = None

            if isinstance(payload, dict):
                servers = payload.get("servers")
                if isinstance(servers, list) and servers and isinstance(servers[0], dict):
                    old_url = str(servers[0].get("url", "")).strip()
                    servers[0]["url"] = url
                    if old_url:
                        # Prefer a surgical text update so comments and most formatting stay intact.
                        pattern = rf"(^\s*-\s+url:\s*[\"']?){re.escape(old_url)}([\"']?\s*$)"
                        candidate, count = re.subn(pattern, rf"\1{url}\2", text, count=1, flags=re.MULTILINE)
                        if count:
                            updated_text = candidate
                    if updated_text is None and _yaml is not None:
                        updated_text = _yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)

            if updated_text is None:
                updated_text = re.sub(r"(^\s*-\s+url:\s*)https://[^\n]+", rf"\1{url}", text, count=1, flags=re.MULTILINE)

            openapi_file.write_text(updated_text, "utf-8")

    def stop_all(self) -> None:
        self._tunnel_restart_count = self._tunnel_max_restarts  # prevent auto-restart during shutdown
        self._stop_process(self.tunnel_proc, "туннель")
        if self.agent_proc is not None:
            self._stop_process(self.agent_proc, "демон")
        elif self._using_external_daemon:
            self.write_log("Внешний демон оставляю запущенным: панель его не запускала.\n")
        self.tunnel_proc = None
        self.agent_proc = None
        self._using_external_daemon = False
        self.last_url = None
        self._tunnel_blocked_reason = None
        self._last_tunnel_failure = None
        self._recovering_tunnel = False
        self._public_check_failures = 0
        self.tunnel_url.set("Туннель: не запущен")
        self.agent_status.set("Демон: не запущен")

    def _stop_process(self, proc: subprocess.Popen | None, label: str) -> None:
        if not proc or proc.poll() is not None:
            return
        self.write_log(f"Останавливаю {label}...\n")
        if IS_WINDOWS:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    # --- Health checks ---

    def check_now(self) -> None:
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        local_ok, local_detail = self._url_ok(f"{LOCAL_URL}/health")
        self.write_log(f"Локальный демон: {'OK ✓' if local_ok else local_detail}\n")
        if self.last_url:
            tunnel_ok, tunnel_detail = self._check_public_gpts_ready()
            self.write_log(f"Публичный URL: {'OK ✓' if tunnel_ok else tunnel_detail}\n")
        elif self._tunnel_blocked_reason:
            self.write_log(f"Публичный URL: {self._tunnel_blocked_reason}\n")
        elif self._last_tunnel_failure:
            self.write_log(f"Публичный URL: {self._describe_tunnel_failure(self._last_tunnel_failure)}\n")
        else:
            self.write_log("Туннель: не запущен\n")

    def _schedule_tunnel_recovery(self, failure: TunnelFailure | None) -> None:
        if self._recovering_tunnel:
            return
        if failure and not failure.recoverable:
            self.write_log(f"Автовосстановление остановлено: {self._describe_tunnel_failure(failure)}\n")
            return
        if self._tunnel_restart_count >= self._tunnel_max_restarts:
            self.write_log("Автовосстановление остановлено: достигнут лимит попыток.\n")
            return
        self._tunnel_restart_count += 1
        delay = RECOVERY_BACKOFF_STEPS_SEC[min(self._tunnel_restart_count - 1, len(RECOVERY_BACKOFF_STEPS_SEC) - 1)]
        self._recovering_tunnel = True
        self.tunnel_url.set("Туннель: восстановление...")
        self.write_log(
            f"Пробую восстановить туннель ({self._tunnel_restart_count}/{self._tunnel_max_restarts}) через {delay} сек...\n"
        )
        threading.Thread(target=self._recover_tunnel_worker, args=(delay,), daemon=True).start()

    def _recover_tunnel_worker(self, delay: int) -> None:
        try:
            time.sleep(delay)
            daemon_alive = self._local_daemon_ready()
            if not daemon_alive:
                self.write_log("Перед восстановлением туннеля локальный демон не отвечает. Пробую поднять всё заново.\n")
                self._start_all_worker()
                return
            self._stop_process(self.tunnel_proc, "туннель")
            self.tunnel_proc = None
            self.last_url = None
            self._public_check_failures = 0
            self._start_tunnel()
        finally:
            self._recovering_tunnel = False

    def _verify_public_url_in_background(self) -> None:
        if self._public_check_running or not self.last_url:
            return
        self._public_check_running = True
        threading.Thread(target=self._public_check_worker, daemon=True).start()

    def _public_check_worker(self) -> None:
        try:
            tunnel_ok, tunnel_detail = self._check_public_gpts_ready()
            if tunnel_ok:
                if self._public_check_failures > 0:
                    self.write_log("Публичный URL снова отвечает.\n")
                self._public_check_failures = 0
                return
            self._public_check_failures += 1
            self.write_log(
                f"Проверка публичного URL не прошла ({self._public_check_failures}/{PUBLIC_CHECK_MAX_FAILURES}): {tunnel_detail}\n"
            )
            if self._public_check_failures >= PUBLIC_CHECK_MAX_FAILURES:
                self._last_tunnel_failure = TunnelFailure(
                    code="public_probe_failed",
                    summary=f"публичный URL не отвечает: {tunnel_detail}",
                    recoverable=True,
                )
                self._schedule_tunnel_recovery(self._last_tunnel_failure)
        finally:
            self._last_public_check_ts = time.time()
            self._public_check_running = False

    def _check_public_gpts_ready(self) -> tuple[bool, str]:
        if not self.last_url:
            return False, "нет URL туннеля"
        return self._url_ok(
            f"{self.last_url}/v1/capabilities",
            attempts=TUNNEL_HEALTH_ATTEMPTS,
            delay_sec=TUNNEL_HEALTH_DELAY_SEC,
            expect_json_key="workspace",
        )

    def _url_ok(
        self,
        url: str,
        attempts: int = 1,
        delay_sec: float = 0.0,
        expect_json_key: str | None = None,
    ) -> tuple[bool, str]:
        last_error = "не отвечает"
        ssl_context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(url)
                token = self.agent_token()
                if token:
                    request.add_header("Authorization", f"Bearer {token}")
                # ngrok free tier shows interstitial page to browsers;
                # setting a non-browser User-Agent + ngrok-skip-browser-warning header bypasses it.
                request.add_header("User-Agent", "GPTAgent/1.0")
                request.add_header("ngrok-skip-browser-warning", "true")
                with urllib.request.urlopen(request, timeout=TUNNEL_HEALTH_TIMEOUT_SEC, context=ssl_context) as response:
                    body = response.read(2000).decode("utf-8", errors="replace")
                    if not (200 <= response.status < 300):
                        last_error = f"HTTP {response.status}"
                    elif expect_json_key:
                        try:
                            payload = json.loads(body)
                        except json.JSONDecodeError:
                            last_error = "ответ не похож на JSON (возможно interstitial-страница ngrok)"
                        else:
                            if expect_json_key in payload:
                                return True, "OK"
                            last_error = f"нет поля {expect_json_key}"
                    else:
                        return True, "OK"
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", None)
                last_error = f"ошибка сети: {reason or exc}"
            except TimeoutError:
                last_error = "таймаут"

            if attempt < attempts:
                time.sleep(delay_sec)
        return False, last_error

    # --- Monitoring: auto-restart tunnel if it dies ---

    def _poll_status(self) -> None:
        # Daemon status
        if self.agent_proc and self.agent_proc.poll() is None:
            self.agent_status.set("Демон: работает на http://127.0.0.1:8787")
        elif self._using_external_daemon and self._local_daemon_ready() and self._current_project_owns_port_8787():
            self.agent_status.set("Демон: уже запущен на http://127.0.0.1:8787")
        elif self._local_daemon_ready() and not self._current_project_owns_port_8787():
            self._using_external_daemon = False
            status_text = (
                "Демон: на порту 8787 уже есть процесс, но на Windows владелец не подтверждён"
                if IS_WINDOWS
                else "Демон: на порту 8787 висит другой проект"
            )
            self.agent_status.set(status_text)
        else:
            self._using_external_daemon = False
            self.agent_status.set("Демон: не запущен")

        # Tunnel auto-restart: if daemon is alive but tunnel died, restart tunnel
        daemon_alive = (self.agent_proc and self.agent_proc.poll() is None) or self._using_external_daemon
        tunnel_dead = self.tunnel_proc is None or self.tunnel_proc.poll() is not None
        if (
            daemon_alive
            and tunnel_dead
            and self.last_url is None
            and self._tunnel_blocked_reason is None
            and not self._recovering_tunnel
        ):
            if self.tunnel_proc is not None:
                self._schedule_tunnel_recovery(self._last_tunnel_failure)

        tunnel_alive = self.tunnel_proc is not None and self.tunnel_proc.poll() is None and self.last_url is not None
        if tunnel_alive and (time.time() - self._last_public_check_ts) >= PUBLIC_CHECK_INTERVAL_SEC:
            self._verify_public_url_in_background()

        self.root.after(TUNNEL_MONITOR_INTERVAL_MS, self._poll_status)

    # --- Clipboard ---

    def copy_url(self) -> None:
        if not self.last_url:
            self.write_log("URL ещё нет. Сначала нажми «Запустить».\n")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_url)
        self.write_log(f"Скопировал URL: {self.last_url}\n")

    def open_project_folder(self) -> None:
        """Open the project folder in Explorer/Finder and log which files to use for GPT setup."""
        try:
            if IS_WINDOWS:
                subprocess.Popen(["explorer", str(PROJECT_DIR)])
            elif shutil.which("open"):
                subprocess.Popen(["open", str(PROJECT_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(PROJECT_DIR)])
        except Exception as exc:
            self.write_log(f"Не смог открыть папку: {exc}\n")
            return
        openapi = PROJECT_DIR / "openapi.gpts.yaml"
        instructions = PROJECT_DIR / "gpts" / "system_instructions.txt"
        knowledge_dir = PROJECT_DIR / "gpts" / "knowledge"
        token = self.agent_token()
        token_hint = f"{token[:6]}...{token[-4:]}" if len(token) > 12 else "(не задан)"
        self.write_log(
            f"Открыл папку: {PROJECT_DIR}\n"
            "\nФайлы для настройки GPT в ChatGPT:\n"
            f"  Instructions → {instructions.name}  "
            f"({'есть' if instructions.exists() else 'НЕТ'})\n"
            f"  Knowledge    → папка {knowledge_dir.name}/  "
            f"({'есть' if knowledge_dir.exists() else 'НЕТ'})\n"
            f"  Actions      → {openapi.name}  "
            f"({'есть' if openapi.exists() else 'НЕТ'})\n"
            f"  Auth Bearer  → AGENT_TOKEN = {token_hint}\n"
        )

    def open_env_file(self) -> None:
        if not ENV_FILE.exists():
            self.write_log(f"Файл не найден: {ENV_FILE}\n")
            return
        try:
            if IS_WINDOWS:
                os.startfile(str(ENV_FILE))  # type: ignore[attr-defined]
                self.write_log(f"Открыл файл настроек: {ENV_FILE}\n")
            elif shutil.which("open"):
                subprocess.Popen(["open", str(ENV_FILE)], cwd=PROJECT_DIR)
                self.write_log(f"Открыл файл настроек: {ENV_FILE}\n")
            else:
                self.write_log(
                    "Не нашёл системную команду open. Открой этот файл вручную:\n"
                    f"{ENV_FILE}\n"
                )
        except Exception as exc:
            self.write_log(
                "Не смог открыть файл автоматически.\n"
                f"Открой его вручную: {ENV_FILE}\n"
                f"Техническая причина: {exc}\n"
            )

    # --- Lifecycle ---

    def on_close(self) -> None:
        self.stop_all()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ControlPanel().run()
