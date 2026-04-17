#!/usr/bin/env python3
# Second Lane
# Copyright (c) 2026 Yurii Slepnev
# Licensed under the Apache License, Version 2.0.
# Official: https://t.me/yurii_yurii86 | https://youtube.com/@yurii_yurii86 | https://instagram.com/yurii_yurii86

from __future__ import annotations

import ipaddress
import json
import os
import queue
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from app.core.config import PROJECT_DIR, Settings, load_settings, validate_runtime_settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.project_memory import (
    append_jsonl,
    create_checkpoint,
    ensure_memory,
    list_checkpoints,
    rollback_checkpoint,
    snapshot_memory,
    summarize_changes,
    write_json,
    write_markdown_section,
)
from app.core.providers import load_providers
from app.core.security import require_auth
from app.core.utils import ensure_parent, list_dir, now_ts, resolve_allowed_path, run_subprocess, search_text, unified_diff


settings = load_settings()
validate_runtime_settings(settings)
app = FastAPI(
    title="Second Lane API",
    version="3.1.0",
    description=(
        "Second Lane — local GPT Actions runtime by Yurii Slepnev. "
        "Telegram: https://t.me/yurii_yurii86 | "
        "YouTube: https://youtube.com/@yurii_yurii86 | "
        "Instagram: https://instagram.com/yurii_yurii86 | "
        "License: Apache-2.0"
    ),
)
PROCESS_REGISTRY: dict[int, dict[str, Any]] = {}
IS_WINDOWS = os.name == "nt"


_RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "600"))
_RATE_LIMITER = SlidingWindowLimiter(max_requests=_RATE_LIMIT_MAX, window_seconds=60.0)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if _RATE_LIMIT_MAX <= 0 or not request.url.path.startswith("/v1/"):
        return await call_next(request)
    client = request.client.host if request.client else "unknown"
    allowed, retry_after = _RATE_LIMITER.allow(client)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded", "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


_initialized_dbs: set[str] = set()


def _ensure_db(db_path: Path) -> None:
    key = str(db_path)
    if key in _initialized_dbs:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS events (id integer primary key autoincrement, ts integer not null, kind text not null, payload text not null)"
        )
        conn.commit()
    _initialized_dbs.add(key)


def _append_process_log(entry: dict[str, Any], text: str) -> None:
    if not text:
        return
    with entry["log_lock"]:
        chunks: list[str] = entry.setdefault("log_chunks", [])
        chunks.append(text)
        total = entry.get("log_size", 0) + len(text)
        max_chars = settings.max_output_chars
        while chunks and total > max_chars:
            removed = chunks.pop(0)
            total -= len(removed)
        entry["log_size"] = total


_LEGACY_CONSOLE_ENCODINGS = ("cp866", "cp1251")


def _decode_process_bytes(chunk: bytes, carry: bytes = b"") -> tuple[str, bytes]:
    """Decode subprocess stdout bytes with a Windows-friendly fallback cascade.

    Strategy:
      1. Try strict utf-8. If it succeeds, we are done.
      2. If utf-8 fails only at the very tail (≤3 trailing bytes), the chunk
         likely split a multibyte character — return the valid prefix and keep
         the tail as *carry* for the next read.
      3. Otherwise try legacy Windows console encodings (cp866 OEM, cp1251 ANSI)
         that cmd.exe / ping / net use on ru-RU systems.
      4. As last resort, utf-8 with errors='replace' so we never raise.
    """
    buffer = carry + chunk
    if not buffer:
        return "", b""
    try:
        return buffer.decode("utf-8"), b""
    except UnicodeDecodeError as exc:
        # Tail split across read() boundary — keep up to 3 bytes as carry.
        if exc.start >= len(buffer) - 3 and exc.start > 0 and chunk:
            head = buffer[: exc.start]
            tail = buffer[exc.start :]
            return head.decode("utf-8"), tail
    for enc in _LEGACY_CONSOLE_ENCODINGS:
        try:
            return buffer.decode(enc), b""
        except UnicodeDecodeError:
            continue
    return buffer.decode("utf-8", errors="replace"), b""


def _drain_process_output(process_id: int) -> None:
    item = PROCESS_REGISTRY.get(process_id)
    if not item:
        return
    proc: subprocess.Popen = item["proc"]
    if proc.stdout is None:
        item["stdout_closed"] = True
        return
    carry = b""
    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            text, carry = _decode_process_bytes(chunk, carry)
            if text:
                _append_process_log(item, text)
        if carry:
            tail, _ = _decode_process_bytes(b"", carry)
            if tail:
                _append_process_log(item, tail)
    finally:
        item["stdout_closed"] = True


def _drain_binary_stream(stream: Any, chunk_queue: queue.Queue[bytes | None]) -> None:
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            chunk_queue.put(chunk)
    finally:
        chunk_queue.put(None)


def auth_dependency(authorization: str | None = Header(default=None)) -> None:
    require_auth(settings, authorization)


def db_log(kind: str, payload: dict[str, Any]) -> None:
    _ensure_db(settings.state_db_path)
    with sqlite3.connect(settings.state_db_path) as conn:
        conn.execute(
            "INSERT INTO events(ts, kind, payload) VALUES (?, ?, ?)",
            (now_ts(), kind, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()


class PathReq(BaseModel):
    path: str


class InspectReq(PathReq):
    agent_name: str | None = None
    change_kind: str | None = None


class InitMemoryReq(PathReq):
    project_name: str | None = None
    agent_name: str | None = None


class SnapshotReq(PathReq):
    agent_name: str | None = None
    change_kind: str | None = None


class CheckpointReq(PathReq):
    include_paths: list[str] = Field(default_factory=list)
    note: str | None = None


class RollbackReq(PathReq):
    checkpoint_id: str | None = None


class SummarizeReq(PathReq):
    checkpoint_id: str | None = None
    include_paths: list[str] | None = None


class SafePatchReq(PathReq):
    file_path: str
    search_text: str
    replace_text: str
    expected_occurrences: int = 1
    note: str | None = None


class SafePatchVerifyReq(SafePatchReq):
    verify_argv: list[str]
    verify_cwd: str | None = None
    verify_timeout_sec: int = 30
    rollback_on_failure: bool = True


class PatchOperation(BaseModel):
    search_text: str
    replace_text: str
    expected_occurrences: int = 1


class ApplyPatchReq(PathReq):
    file_path: str
    operations: list[PatchOperation] = Field(default_factory=list)
    note: str | None = None


class MultiFilePatchItem(BaseModel):
    file_path: str
    operations: list[PatchOperation] = Field(default_factory=list)


class MultiFilePatchVerifyReq(PathReq):
    patches: list[MultiFilePatchItem] = Field(default_factory=list)
    verify_argv: list[str]
    verify_cwd: str | None = None
    verify_timeout_sec: int = 30
    rollback_on_failure: bool = True
    note: str | None = None


class RunTestReq(PathReq):
    command: list[str] | None = None
    cwd: str | None = None
    test_target: str | None = None
    timeout_sec: int = 120


class AnalyzeReq(PathReq):
    argv: list[str]
    cwd: str | None = None
    timeout_sec: int = 30


class RunServiceReq(PathReq):
    service_argv: list[str]
    smoke_argv: list[str]
    service_cwd: str | None = None
    smoke_cwd: str | None = None
    startup_text: str | None = None
    startup_timeout_sec: int = 20
    startup_wait_sec: float = 0
    smoke_timeout_sec: int = 20


class RecordSessionReq(PathReq):
    session_id: str | None = None
    agent_name: str
    user_goal: str
    scope: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    summary: str
    result: str
    next_step: str
    started_at: str | None = None
    ended_at: str | None = None


class RecordChangeReq(PathReq):
    change_id: str | None = None
    session_id: str
    kind: str
    paths: list[str] = Field(default_factory=list)
    reason: str
    verification: list[str] = Field(default_factory=list)
    status: str
    timestamp: str | None = None


class HandoffReq(PathReq):
    current_state: str
    last_verified_step: str
    next_suggested_step: str
    main_risks: list[str] = Field(default_factory=list)


class ActiveTasksReq(PathReq):
    active_tasks: list[dict] = Field(default_factory=list)
    open_risks: list[dict] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_resume_hint: str


class SystemStateReq(PathReq):
    project_name: str
    project_type: str
    project_status: str
    entrypoints: list[str] = Field(default_factory=list)
    run_commands: list[str] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    key_paths: list[str] = Field(default_factory=list)
    external_services: list[str] = Field(default_factory=list)
    load_bearing_files: list[str] = Field(default_factory=list)
    environment_constraints: list[str] = Field(default_factory=list)
    security_constraints: list[str] = Field(default_factory=list)
    workflow_constraints: list[str] = Field(default_factory=list)


class FinalizeReq(PathReq):
    session_id: str | None = None
    agent_name: str
    user_goal: str
    scope: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    summary: str
    result: str
    next_step: str
    started_at: str | None = None
    ended_at: str | None = None
    change: dict | None = None
    system_state: dict | None = None
    handoff: dict
    active_tasks: dict


class SessionRecord(BaseModel):
    path: str
    session_id: str
    agent_name: str
    user_goal: str
    scope: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    summary: str
    result: str
    next_step: str
    started_at: str | None = None
    ended_at: str | None = None


class ChangeRecord(BaseModel):
    path: str
    change_id: str
    session_id: str
    kind: str
    paths: list[str] = Field(default_factory=list)
    reason: str
    verification: list[str] = Field(default_factory=list)
    status: str
    timestamp: str | None = None


class HandoffState(BaseModel):
    current_state: str
    last_verified_step: str
    next_suggested_step: str
    main_risks: list[str] = Field(default_factory=list)


class ActiveTasksState(BaseModel):
    active_tasks: list[dict[str, Any]] = Field(default_factory=list)
    open_risks: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_resume_hint: str


class SystemStatePayload(BaseModel):
    project_name: str
    project_type: str
    project_status: str
    entrypoints: list[str] = Field(default_factory=list)
    run_commands: list[str] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    key_paths: list[str] = Field(default_factory=list)
    external_services: list[str] = Field(default_factory=list)
    load_bearing_files: list[str] = Field(default_factory=list)
    environment_constraints: list[str] = Field(default_factory=list)
    security_constraints: list[str] = Field(default_factory=list)
    workflow_constraints: list[str] = Field(default_factory=list)


class RecordSessionResp(BaseModel):
    ok: bool
    session: SessionRecord


class RecordChangeResp(BaseModel):
    ok: bool
    change: ChangeRecord


class UpdateHandoffResp(BaseModel):
    ok: bool
    handoff: HandoffState


class UpdateActiveTasksResp(BaseModel):
    ok: bool
    active_tasks: ActiveTasksState


class UpdateSystemStateResp(BaseModel):
    ok: bool
    system_state: SystemStatePayload


class FinalizeWorkResp(BaseModel):
    ok: bool
    session: SessionRecord


class ReadReq(BaseModel):
    path: str


class WriteReq(BaseModel):
    path: str
    content: str


class SearchReq(BaseModel):
    root: str
    query: str
    max_results: int = 50


class ListDirReq(BaseModel):
    path: str
    max_entries: int = 200


class ExecReq(BaseModel):
    argv: list[str]
    cwd: str
    timeout_sec: int = 30


class ProcessReq(BaseModel):
    process_id: int
    max_chars: int = 50000


class GitReq(BaseModel):
    cwd: str


class HttpReq(BaseModel):
    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class BrowserReq(BaseModel):
    url: str


class OpenPathReq(BaseModel):
    path: str
    reveal: bool = False


class OpenAppReq(BaseModel):
    app_name: str
    args: list[str] = Field(default_factory=list)


class GuiActionReq(BaseModel):
    action: str
    app_name: str | None = None
    url: str | None = None
    path: str | None = None


class SshReq(BaseModel):
    host: str
    username: str
    password: SecretStr | None = None
    command: str
    port: int = 22


def _inspect_project(path: Path) -> dict[str, Any]:
    names = sorted(item.name for item in path.iterdir())
    important = []
    for candidate in ("package.json", "pyproject.toml", "requirements.txt", "Dockerfile", "docker-compose.yml", "README.md"):
        if (path / candidate).exists():
            important.append(candidate)
    project_type = "unknown"
    hints: list[str] = []
    run_commands: list[str] = []
    test_commands: list[str] = []
    if (path / "requirements.txt").exists() or (path / "pyproject.toml").exists():
        project_type = "python"
        hints.append("python")
        test_commands.append("pytest")
    if (path / "app" / "main.py").exists():
        hints.extend(["fastapi", "backend"])
        run_commands.append("uvicorn app.main:app --reload")
    if (path / "package.json").exists():
        hints.append("node")
        project_type = "node"
    if (path / ".git").exists():
        hints.append("git")
    return {
        "path": str(path),
        "project_type": project_type,
        "files": names,
        "hints": sorted(set(hints)),
        "commands": {"run": run_commands, "test": test_commands},
        "important_files": important,
    }


def _classify_failure(output: str) -> str:
    lowered = output.lower()
    # Dependency / import problems
    if "module not found" in lowered or "no module named" in lowered:
        return "missing dependency"
    if "importerror" in lowered or "cannot import name" in lowered:
        return "import error"
    if "cannot find module" in lowered:
        return "missing dependency"
    # Syntax / parse
    if "syntaxerror" in lowered or "indentationerror" in lowered or "taberror" in lowered:
        return "syntax error"
    if "parse error" in lowered or "parsing error" in lowered:
        return "syntax error"
    # Filesystem / permissions / executables
    if "permission denied" in lowered or "eacces" in lowered:
        return "permission issue"
    if "command not found" in lowered or "is not recognized as an internal or external command" in lowered:
        return "missing executable"
    if "no such file or directory" in lowered or "enoent" in lowered:
        return "missing file"
    # Network / ports
    if "address already in use" in lowered or "eaddrinuse" in lowered:
        return "port already in use"
    if "connection refused" in lowered or "econnrefused" in lowered:
        return "connection refused"
    if "connection timed out" in lowered or "etimedout" in lowered:
        return "network timeout"
    # Test frameworks
    if "assertionerror" in lowered:
        return "assertion failure"
    if "failed" in lowered and ("pytest" in lowered or "=== failures ===" in lowered or "short test summary info" in lowered):
        return "test failure"
    if "tests failed" in lowered or "jest" in lowered and "fail" in lowered:
        return "test failure"
    # Runtime
    if "traceback (most recent call last)" in lowered:
        return "runtime exception"
    if "segmentation fault" in lowered or "core dumped" in lowered:
        return "segfault"
    if "out of memory" in lowered or "memoryerror" in lowered:
        return "out of memory"
    # Build tools
    if "npm err!" in lowered or "yarn error" in lowered:
        return "build tool failure"
    if "error ts" in lowered or ": error ts" in lowered:
        return "typescript error"
    if "make: ***" in lowered or "makefile:" in lowered and "error" in lowered:
        return "build tool failure"
    # Silent non-zero exit
    if not lowered.strip():
        return "silent failure"
    return "unknown"


def _resolve_project_file(project_root: Path, file_path: str) -> Path:
    root_resolved = project_root.resolve()
    target = (project_root / file_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="File path escapes project root") from exc
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {file_path}")
    return target


def _safe_patch(project_root: Path, file_path: str, search_text: str, replace_text: str, expected_occurrences: int) -> dict:
    target = _resolve_project_file(project_root, file_path)
    before = target.read_text("utf-8")
    count = before.count(search_text)
    if count != expected_occurrences:
        raise HTTPException(status_code=400, detail=f"Expected {expected_occurrences} occurrences, found {count}")
    after = before.replace(search_text, replace_text)
    target.write_text(after, "utf-8")
    return {"path": file_path, "occurrences": count, "diff": unified_diff(before, after, file_path, file_path)}


def _apply_patch_operations(project_root: Path, file_path: str, operations: list[PatchOperation]) -> dict[str, Any]:
    if not operations:
        raise HTTPException(status_code=400, detail=f"No patch operations provided for {file_path}")
    target = _resolve_project_file(project_root, file_path)
    before = target.read_text("utf-8")
    after = before
    op_results: list[dict[str, Any]] = []
    for idx, operation in enumerate(operations, start=1):
        count = after.count(operation.search_text)
        if count != operation.expected_occurrences:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Patch operation {idx} for {file_path} expected {operation.expected_occurrences} "
                    f"occurrences, found {count}"
                ),
            )
        after = after.replace(operation.search_text, operation.replace_text)
        op_results.append(
            {
                "index": idx,
                "expected_occurrences": operation.expected_occurrences,
                "applied_occurrences": count,
                "search_length": len(operation.search_text),
                "replace_length": len(operation.replace_text),
            }
        )
    target.write_text(after, "utf-8")
    return {
        "path": file_path,
        "changed": before != after,
        "operation_count": len(operations),
        "operations": op_results,
        "diff": unified_diff(before, after, file_path, file_path),
    }


def _ssh_host_matches_cidrs(host: str, cidrs: list[str]) -> bool:
    if not cidrs:
        return False
    networks = []
    for raw in cidrs:
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    if not networks:
        return False
    candidate_ips: set[str] = set()
    try:
        candidate_ips.add(str(ipaddress.ip_address(host)))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            infos = []
        for info in infos:
            addr = info[4][0]
            try:
                candidate_ips.add(str(ipaddress.ip_address(addr)))
            except ValueError:
                continue
    for raw_ip in candidate_ips:
        ip = ipaddress.ip_address(raw_ip)
        if any(ip in network for network in networks):
            return True
    return False


def _ssh_host_allowed(host: str, settings: Settings) -> bool:
    return host in settings.ssh_allowed_hosts or _ssh_host_matches_cidrs(host, settings.ssh_allowed_cidrs)


def _load_known_ssh_hosts(client: Any, settings: Settings) -> None:
    client.load_system_host_keys()
    known_hosts_path = Path(settings.ssh_known_hosts_path).expanduser()
    if known_hosts_path.exists():
        client.load_host_keys(str(known_hosts_path))
    if not client.get_host_keys():
        raise HTTPException(status_code=500, detail="No SSH known_hosts entries are loaded")


def _detect_test_command(project_root: Path, cwd: Path, command: list[str] | None, test_target: str | None) -> tuple[list[str], str]:
    if command:
        argv = list(command)
        if test_target:
            argv.append(test_target)
        return argv, "explicit-command"
    python_markers = ("pyproject.toml", "requirements.txt")
    if any((cwd / name).exists() for name in python_markers) or any((project_root / name).exists() for name in python_markers):
        argv = [sys.executable, "-m", "pytest", "-q"]
        if test_target:
            argv.append(test_target)
        return argv, "python-pytest"
    if (cwd / "tests").exists() or (project_root / "tests").exists():
        argv = [sys.executable, "-m", "pytest", "-q"]
        if test_target:
            argv.append(test_target)
        return argv, "tests-dir-pytest"
    if (cwd / "package.json").exists() or (project_root / "package.json").exists():
        argv = ["npm", "test"]
        if test_target:
            argv.extend(["--", test_target])
        return argv, "node-npm-test"
    if (cwd / "Makefile").exists() or (project_root / "Makefile").exists():
        return ["make", "test"], "make-test"
    raise HTTPException(status_code=400, detail="Could not infer a test command. Provide command explicitly.")


def _ensure_write_size_limit(content: str) -> None:
    content_size = len(content.encode("utf-8"))
    if content_size > settings.max_file_bytes:
        raise HTTPException(status_code=413, detail="file too large")


def _new_record_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _open_url_with_system(url: str) -> None:
    if IS_WINDOWS:
        os.startfile(url)  # type: ignore[attr-defined]
        return
    if shutil.which("open"):
        subprocess.Popen(["open", url], cwd=str(PROJECT_DIR))
        return
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url], cwd=str(PROJECT_DIR))
        return
    raise HTTPException(status_code=500, detail="no system browser opener available")


def _open_path_with_system(path: Path, reveal: bool) -> None:
    if IS_WINDOWS:
        if reveal:
            subprocess.Popen(["explorer", f"/select,{path}"], cwd=str(PROJECT_DIR))
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if shutil.which("open"):
        cmd = ["open", "-R", str(path)] if reveal else ["open", str(path)]
        subprocess.Popen(cmd, cwd=str(PROJECT_DIR))
        return
    if shutil.which("xdg-open") and not reveal:
        subprocess.Popen(["xdg-open", str(path)], cwd=str(PROJECT_DIR))
        return
    raise HTTPException(status_code=500, detail="no system path opener available")


def _open_app_with_system(app_name: str, args: list[str]) -> None:
    if IS_WINDOWS:
        try:
            subprocess.Popen([app_name, *args], cwd=str(PROJECT_DIR))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=f"app not found: {exc.filename or app_name}") from exc
        return
    if shutil.which("open"):
        subprocess.Popen(["open", "-a", app_name, *args], cwd=str(PROJECT_DIR))
        return
    raise HTTPException(status_code=500, detail="no system app opener available")


@app.get("/health", operation_id="health")
def health(_auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    return {"ok": True, "service": "second-lane", "time": now_ts()}


@app.get("/v1/capabilities", operation_id="getCapabilities")
def get_capabilities(_auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    return {
        "workspace": True,
        "exec": True,
        "git": True,
        "http": True,
        "ssh": True,
        "browser": True,
        "system": True,
        "project_memory": True,
        "workspace_roots": [str(item) for item in settings.workspace_roots],
        "ssh_allowed_hosts": settings.ssh_allowed_hosts,
        "ssh_allowed_cidrs": settings.ssh_allowed_cidrs,
        "gui_allowed_apps": settings.gui_allowed_apps,
        "limits": {
            "max_output_chars": settings.max_output_chars,
            "max_file_bytes": settings.max_file_bytes,
            "default_timeout_sec": settings.default_timeout_sec,
        },
    }


@app.get("/v1/providers", operation_id="getProviders")
def get_providers(_auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    return {"providers": load_providers(settings.enabled_provider_manifests)}


@app.post("/v1/flows/inspect_project", operation_id="inspectProject")
def inspect_project(req: InspectReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="path is not a directory")
    payload = _inspect_project(root)
    db_log("inspect_project", payload)
    return payload


@app.post("/v1/project/init_memory")
def init_memory(req: InitMemoryReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    mem = ensure_memory(root, req.project_name)
    return {"ok": True, "memory_dir": str(mem)}


@app.post("/v1/project/get_memory_snapshot")
def get_memory_snapshot(req: SnapshotReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    return {"ok": True, "snapshot": snapshot_memory(root)}


@app.post("/v1/project/ensure_memory", operation_id="ensureProjectMemory")
def ensure_project_memory(req: InitMemoryReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    ensure_memory(root, req.project_name)
    return {"ok": True, "snapshot": snapshot_memory(root)}


@app.post("/v1/project/create_checkpoint")
def create_project_checkpoint(req: CheckpointReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    return create_checkpoint(root, req.include_paths, req.note)


@app.post("/v1/project/list_checkpoints")
def list_project_checkpoints(req: PathReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    return {"checkpoints": list_checkpoints(root)}


@app.post("/v1/project/rollback_checkpoint")
def rollback_project_checkpoint(req: RollbackReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    return rollback_checkpoint(root, req.checkpoint_id)


@app.post("/v1/project/summarize_changes")
def summarize_project_changes(req: SummarizeReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    return summarize_changes(root, req.checkpoint_id, req.include_paths)


@app.post("/v1/project/safe_patch_file")
def safe_patch_project_file(req: SafePatchReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    cp = create_checkpoint(root, [req.file_path], req.note)
    patch = _safe_patch(root, req.file_path, req.search_text, req.replace_text, req.expected_occurrences)
    return {"ok": True, "checkpoint": cp, "patch": patch}


@app.post("/v1/project/safe_patch_and_verify", operation_id="safePatchAndVerifyProjectFile")
def safe_patch_and_verify(req: SafePatchVerifyReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    cp = create_checkpoint(root, [req.file_path], req.note)
    patch = _safe_patch(root, req.file_path, req.search_text, req.replace_text, req.expected_occurrences)
    verify_cwd = resolve_allowed_path(settings, req.verify_cwd) if req.verify_cwd else root
    verify = run_subprocess(req.verify_argv, verify_cwd, req.verify_timeout_sec, settings.max_output_chars)
    if not verify["ok"] and req.rollback_on_failure:
        rollback_project_checkpoint(RollbackReq(path=req.path, checkpoint_id=cp["checkpoint_id"]))
    return {"ok": verify["ok"], "checkpoint": cp, "patch": patch, "verify": verify}


@app.post("/v1/project/apply_patch", operation_id="applyPatch")
def apply_patch(req: ApplyPatchReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    cp = create_checkpoint(root, [req.file_path], req.note)
    patch = _apply_patch_operations(root, req.file_path, req.operations)
    return {"ok": True, "checkpoint": cp, "patch": patch}


@app.post("/v1/project/multi_file_patch_and_verify", operation_id="multiFilePatchAndVerify")
def multi_file_patch_and_verify(req: MultiFilePatchVerifyReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    if not req.patches:
        raise HTTPException(status_code=400, detail="No file patches provided")
    seen: set[str] = set()
    duplicates = sorted({item.file_path for item in req.patches if item.file_path in seen or seen.add(item.file_path)})
    if duplicates:
        raise HTTPException(status_code=400, detail=f"Duplicate file paths in patch set: {', '.join(duplicates)}")
    cp = create_checkpoint(root, [item.file_path for item in req.patches], req.note)
    patch_results: list[dict[str, Any]] = []
    try:
        for item in req.patches:
            patch_results.append(_apply_patch_operations(root, item.file_path, item.operations))
    except HTTPException:
        if req.rollback_on_failure:
            rollback_project_checkpoint(RollbackReq(path=req.path, checkpoint_id=cp["checkpoint_id"]))
        raise
    verify_cwd = resolve_allowed_path(settings, req.verify_cwd) if req.verify_cwd else root
    verify = run_subprocess(req.verify_argv, verify_cwd, req.verify_timeout_sec, settings.max_output_chars)
    rollback_result = None
    if not verify["ok"] and req.rollback_on_failure:
        rollback_result = rollback_project_checkpoint(RollbackReq(path=req.path, checkpoint_id=cp["checkpoint_id"]))
    return {
        "ok": verify["ok"],
        "checkpoint": cp,
        "patches": patch_results,
        "verify": verify,
        "rollback": rollback_result,
    }


@app.post("/v1/project/run_test", operation_id="runTest")
def run_test(req: RunTestReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    cwd = resolve_allowed_path(settings, req.cwd) if req.cwd else root
    argv, strategy = _detect_test_command(root, cwd, req.command, req.test_target)
    result = run_subprocess(argv, cwd, req.timeout_sec, settings.max_output_chars)
    return {
        "ok": result["ok"],
        "strategy": strategy,
        "argv": argv,
        "cwd": str(cwd),
        "test_target": req.test_target,
        "result": result,
    }


@app.post("/v1/project/analyze_build_failure", operation_id="analyzeProjectBuildFailure")
def analyze_build_failure(req: AnalyzeReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    cwd = resolve_allowed_path(settings, req.cwd) if req.cwd else root
    result = run_subprocess(req.argv, cwd, req.timeout_sec, settings.max_output_chars)
    return {"ok": result["ok"], "classification": _classify_failure(result["output"]), "result": result}


@app.post("/v1/project/run_service_and_smoke_check", operation_id="runProjectServiceAndSmokeCheck")
def run_service_and_smoke_check(req: RunServiceReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    service_cwd = resolve_allowed_path(settings, req.service_cwd) if req.service_cwd else root
    smoke_cwd = resolve_allowed_path(settings, req.smoke_cwd) if req.smoke_cwd else root
    try:
        proc = subprocess.Popen(req.service_argv, cwd=str(service_cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False)
    except FileNotFoundError as exc:
        message = f"command not found: {exc.filename or req.service_argv[0]}"
        return {
            "ok": False,
            "started": False,
            "service_output": [],
            "smoke": {
                "ok": False,
                "returncode": None,
                "stdout": "",
                "stderr": message,
                "output": message,
                "command_not_found": True,
            },
        }
    lines: list[str] = []
    started = False
    deadline = time.time() + req.startup_timeout_sec
    chunk_buffer = ""
    try:
        if req.startup_text:
            if proc.stdout is None:
                started = False
            else:
                startup_queue: queue.Queue[bytes | None] = queue.Queue()
                threading.Thread(target=_drain_binary_stream, args=(proc.stdout, startup_queue), daemon=True).start()
                stream_closed = False
                while time.time() < deadline:
                    if stream_closed and startup_queue.empty() and proc.poll() is not None:
                        break
                    try:
                        chunk = startup_queue.get(timeout=0.2)
                    except queue.Empty:
                        if proc.poll() is not None and stream_closed:
                            break
                        continue
                    if chunk is None:
                        stream_closed = True
                        if proc.poll() is not None and startup_queue.empty():
                            break
                        continue
                    text = chunk.decode("utf-8", errors="replace")
                    chunk_buffer += text
                    split_lines = chunk_buffer.splitlines(keepends=True)
                    if split_lines and not split_lines[-1].endswith(("\n", "\r")):
                        chunk_buffer = split_lines.pop()
                    else:
                        chunk_buffer = ""
                    lines.extend(line.rstrip("\r\n") for line in split_lines)
                    if req.startup_text in text or req.startup_text in chunk_buffer:
                        started = True
                        break
        else:
            if req.startup_wait_sec > 0:
                time.sleep(req.startup_wait_sec)
            started = proc.poll() is None
        smoke = run_subprocess(req.smoke_argv, smoke_cwd, req.smoke_timeout_sec, settings.max_output_chars)
        # Readiness fallback: a successful smoke check is a ground-truth proof that the service is up,
        # even if startup_text was never captured (e.g. stderr-only logs, buffering, wrong marker).
        readiness = "startup_text" if started else ("smoke_check" if smoke["ok"] else None)
        started = started or smoke["ok"]
        return {
            "ok": started and smoke["ok"],
            "started": started,
            "readiness": readiness,
            "service_output": lines[-50:],
            "smoke": smoke,
        }
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


@app.post("/v1/project/record_session", response_model=RecordSessionResp)
def record_project_session(req: RecordSessionReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    mem = ensure_memory(root)
    payload = req.model_dump()
    if not payload.get("session_id"):
        payload["session_id"] = _new_record_id("session")
    append_jsonl(mem / "sessions.jsonl", payload)
    return {"ok": True, "session": payload}


@app.post("/v1/project/record_change", response_model=RecordChangeResp)
def record_project_change(req: RecordChangeReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    mem = ensure_memory(root)
    payload = req.model_dump()
    if not payload.get("change_id"):
        payload["change_id"] = _new_record_id("change")
    append_jsonl(mem / "change_log.jsonl", payload)
    return {"ok": True, "change": payload}


@app.post("/v1/project/update_handoff", response_model=UpdateHandoffResp, operation_id="updateProjectHandoff")
def update_project_handoff(req: HandoffReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    mem = ensure_memory(root)
    payload = req.model_dump(exclude={"path"})
    write_markdown_section(
        mem / "handoff.md",
        "Handoff",
        [
            f"- Current state: {payload['current_state']}",
            f"- Last verified step: {payload['last_verified_step']}",
            f"- Next suggested step: {payload['next_suggested_step']}",
            f"- Main risks: {', '.join(payload.get('main_risks', [])) or 'none'}",
        ],
    )
    return {"ok": True, "handoff": payload}


@app.post("/v1/project/update_active_tasks", response_model=UpdateActiveTasksResp, operation_id="updateProjectActiveTasks")
def update_project_active_tasks(req: ActiveTasksReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    mem = ensure_memory(root)
    payload = req.model_dump(exclude={"path"})
    write_json(mem / "active_tasks.json", payload)
    return {"ok": True, "active_tasks": payload}


@app.post("/v1/project/update_system_state", response_model=UpdateSystemStateResp)
def update_project_system_state(req: SystemStateReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.path)
    mem = ensure_memory(root, req.project_name)
    payload = req.model_dump(exclude={"path"})
    write_json(mem / "system_state.json", payload)
    return {"ok": True, "system_state": payload}


@app.post("/v1/project/finalize_work", response_model=FinalizeWorkResp, operation_id="finalizeProjectWork")
def finalize_project_work(req: FinalizeReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    session_payload = RecordSessionReq(
        path=req.path,
        session_id=req.session_id,
        agent_name=req.agent_name,
        user_goal=req.user_goal,
        scope=req.scope,
        files_changed=req.files_changed,
        commands_run=req.commands_run,
        summary=req.summary,
        result=req.result,
        next_step=req.next_step,
        started_at=req.started_at,
        ended_at=req.ended_at,
    )
    session = record_project_session(session_payload)
    if req.change:
        change_payload = RecordChangeReq(path=req.path, session_id=session["session"]["session_id"], **req.change)
        record_project_change(change_payload)
    if req.system_state:
        update_project_system_state(SystemStateReq(path=req.path, **req.system_state))
    update_project_handoff(HandoffReq(path=req.path, **req.handoff))
    update_project_active_tasks(ActiveTasksReq(path=req.path, **req.active_tasks))
    return {"ok": True, "session": session["session"]}


@app.post("/v1/workspace/read_file", operation_id="readFile")
def read_file(req: ReadReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    path = resolve_allowed_path(settings, req.path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if path.stat().st_size > settings.max_file_bytes:
        raise HTTPException(status_code=413, detail="file too large")
    return {"path": str(path), "content": path.read_text("utf-8")}


@app.post("/v1/workspace/write_file", operation_id="writeFile")
def write_file(req: WriteReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    path = resolve_allowed_path(settings, req.path)
    _ensure_write_size_limit(req.content)
    ensure_parent(path)
    path.write_text(req.content, "utf-8")
    db_log("write_file", {"path": str(path)})
    return {"ok": True, "path": str(path)}


@app.post("/v1/workspace/search", operation_id="searchWorkspace")
def search_workspace(req: SearchReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    root = resolve_allowed_path(settings, req.root)
    return {"results": search_text(root, req.query, req.max_results)}


@app.post("/v1/workspace/list_dir", operation_id="listDirectory")
def list_directory(req: ListDirReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    path = resolve_allowed_path(settings, req.path)
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="path is not a directory")
    return {"entries": list_dir(path, req.max_entries)}


@app.post("/v1/exec/run", operation_id="runCommand")
def run_command(req: ExecReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    cwd = resolve_allowed_path(settings, req.cwd)
    db_log("run_command", {"argv": req.argv, "cwd": str(cwd)})
    return run_subprocess(req.argv, cwd, req.timeout_sec, settings.max_output_chars)


@app.post("/v1/exec/start", operation_id="startCommand")
def start_command(req: ExecReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    cwd = resolve_allowed_path(settings, req.cwd)
    try:
        # text=False + manual cascade decoding: Windows consoles (cmd.exe, ping, net...)
        # emit OEM-encoded bytes (cp866 on ru-RU) while Python's default text mode
        # assumes the ANSI/locale codepage. Reading as bytes lets us try utf-8 → cp866
        # → cp1251 and keep Cyrillic logs readable.
        proc = subprocess.Popen(req.argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, bufsize=0)
    except FileNotFoundError as exc:
        message = f"command not found: {exc.filename or req.argv[0]}"
        return {
            "ok": False,
            "process_id": None,
            "returncode": None,
            "stdout": "",
            "stderr": message,
            "output": message,
            "command_not_found": True,
        }
    finished = [pid for pid, item in PROCESS_REGISTRY.items() if item["proc"].poll() is not None and item.get("stdout_closed")]
    for pid in finished:
        del PROCESS_REGISTRY[pid]
    PROCESS_REGISTRY[proc.pid] = {
        "proc": proc,
        "cwd": str(cwd),
        "argv": req.argv,
        "log_chunks": [],
        "log_size": 0,
        "log_lock": threading.Lock(),
        "stdout_closed": False,
    }
    threading.Thread(target=_drain_process_output, args=(proc.pid,), daemon=True).start()
    db_log("start_command", {"argv": req.argv, "cwd": str(cwd), "process_id": proc.pid})
    return {"ok": True, "process_id": proc.pid}


@app.post("/v1/exec/status", operation_id="getCommandStatus")
def get_command_status(req: ProcessReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    item = PROCESS_REGISTRY.get(req.process_id)
    if not item:
        raise HTTPException(status_code=404, detail="process not found")
    proc: subprocess.Popen = item["proc"]
    return {"process_id": req.process_id, "running": proc.poll() is None, "returncode": proc.poll()}


@app.post("/v1/exec/logs", operation_id="getCommandLogs")
def get_command_logs(req: ProcessReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    item = PROCESS_REGISTRY.get(req.process_id)
    if not item:
        raise HTTPException(status_code=404, detail="process not found")
    with item["log_lock"]:
        output = "".join(item.get("log_chunks", []))
    if len(output) > req.max_chars:
        output = output[-req.max_chars :]
    return {"process_id": req.process_id, "logs": output, "stdout_closed": item.get("stdout_closed", False)}


@app.post("/v1/exec/stop", operation_id="stopCommand")
def stop_command(req: ProcessReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    item = PROCESS_REGISTRY.get(req.process_id)
    if not item:
        raise HTTPException(status_code=404, detail="process not found")
    proc: subprocess.Popen = item["proc"]
    if proc.poll() is None:
        proc.terminate()
    return {"ok": True, "process_id": req.process_id}


def _find_git_root(cwd: Path) -> Path | None:
    """Walk up from cwd looking for a .git directory/file. Returns the repo root or None."""
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _not_a_repo_response(cwd: Path) -> dict[str, Any]:
    message = f"not a git repository: {cwd}"
    return {
        "ok": False,
        "not_a_repo": True,
        "returncode": None,
        "stdout": "",
        "stderr": message,
        "output": message,
        "cwd": str(cwd),
    }


@app.post("/v1/git/status", operation_id="gitStatus")
def git_status(req: GitReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    cwd = resolve_allowed_path(settings, req.cwd)
    if _find_git_root(cwd) is None:
        return _not_a_repo_response(cwd)
    return run_subprocess(["git", "status", "--short"], cwd, settings.default_timeout_sec, settings.max_output_chars)


@app.post("/v1/git/diff", operation_id="gitDiff")
def git_diff(req: GitReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    cwd = resolve_allowed_path(settings, req.cwd)
    if _find_git_root(cwd) is None:
        return _not_a_repo_response(cwd)
    return run_subprocess(["git", "diff"], cwd, settings.default_timeout_sec, settings.max_output_chars)


@app.post("/v1/http/request", operation_id="httpRequest")
def http_request(req: HttpReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    import httpx

    response = httpx.request(req.method, req.url, headers=req.headers, content=req.body, timeout=settings.default_timeout_sec)
    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "text": response.text[: settings.max_output_chars],
    }


@app.post("/v1/browser/open_url")
def open_browser_url(req: BrowserReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    _open_url_with_system(req.url)
    return {"ok": True, "url": req.url}


@app.post("/v1/system/open_path", operation_id="openSystemPath")
def open_system_path(req: OpenPathReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    path = resolve_allowed_path(settings, req.path)
    _open_path_with_system(path, req.reveal)
    return {"ok": True, "path": str(path)}


@app.post("/v1/system/open_app", operation_id="openSystemApp")
def open_system_app(req: OpenAppReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    if req.app_name not in settings.gui_allowed_apps:
        raise HTTPException(status_code=403, detail="app is not allowlisted")
    _open_app_with_system(req.app_name, req.args)
    return {"ok": True, "app_name": req.app_name}


@app.post("/v1/system/gui_action")
def run_gui_action(req: GuiActionReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    if req.action == "open_url" and req.url:
        return open_browser_url(BrowserReq(url=req.url))
    if req.action == "open_path" and req.path:
        return open_system_path(OpenPathReq(path=req.path, reveal=False))
    if req.action == "reveal_path" and req.path:
        return open_system_path(OpenPathReq(path=req.path, reveal=True))
    if req.action == "open_app" and req.app_name:
        return open_system_app(OpenAppReq(app_name=req.app_name))
    raise HTTPException(status_code=400, detail="unsupported gui action")


@app.post("/v1/ssh/exec", operation_id="sshExec")
def ssh_exec(req: SshReq, _auth: None = Depends(auth_dependency)) -> dict[str, Any]:
    import paramiko

    if not _ssh_host_allowed(req.host, settings):
        raise HTTPException(status_code=403, detail="SSH host is not allowlisted")
    client = paramiko.SSHClient()
    _load_known_ssh_hosts(client, settings)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    password_value = req.password.get_secret_value() if req.password is not None else None
    try:
        client.connect(req.host, port=req.port, username=req.username, password=password_value, timeout=settings.default_timeout_sec)
        _, stdout, stderr = client.exec_command(req.command, timeout=settings.default_timeout_sec)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return {"ok": True, "stdout": out[: settings.max_output_chars], "stderr": err[: settings.max_output_chars]}
    finally:
        client.close()
