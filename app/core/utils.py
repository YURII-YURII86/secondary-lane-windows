# Second Lane
# Copyright (c) 2026 Yurii Slepnev
# Licensed under the Apache License, Version 2.0.
# Official: https://t.me/yurii_yurii86 | https://youtube.com/@yurii_yurii86 | https://instagram.com/yurii_yurii86
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import HTTPException, status

from .config import Settings


def now_ts() -> int:
    return int(time.time())


def resolve_allowed_path(settings: Settings, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve()
    for root in settings.workspace_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Path is outside WORKSPACE_ROOTS")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def limited_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...truncated..."


def run_subprocess(argv: list[str], cwd: Path, timeout_sec: int, max_output_chars: int) -> dict:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": limited_text(completed.stdout or "", max_output_chars),
            "stderr": limited_text(completed.stderr or "", max_output_chars),
            "output": limited_text(output, max_output_chars),
        }
    except FileNotFoundError as exc:
        message = f"command not found: {exc.filename or argv[0]}"
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": message,
            "output": limited_text(message, max_output_chars),
            "command_not_found": True,
        }
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "timeout",
            "output": limited_text(output or "timeout", max_output_chars),
            "timed_out": True,
        }


def list_dir(path: Path, max_entries: int = 200) -> list[dict]:
    items = []
    for entry in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:max_entries]:
        items.append(
            {
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.exists() else 0,
            }
        )
    return items


def search_text(root: Path, query: str, max_results: int = 50) -> list[dict]:
    rg = shutil.which("rg")
    if rg:
        completed = subprocess.run(
            [rg, "-n", "-S", query, str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        results = []
        for line in completed.stdout.splitlines()[:max_results]:
            match = re.match(r"^(.*?):(\d+):(.*)$", line)
            if not match:
                continue
            file_path, line_no, snippet = match.groups()
            results.append({"path": file_path, "line": int(line_no), "snippet": snippet})
        return results

    results = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if query in line:
                results.append({"path": str(file_path), "line": idx, "snippet": line})
                if len(results) >= max_results:
                    return results
    return results


def unified_diff(before: str, after: str, from_name: str, to_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=from_name,
            tofile=to_name,
        )
    )
