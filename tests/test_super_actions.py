from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
import yaml
import app.main as main
from app.core import utils as core_utils


AUTH = {"Authorization": "Bearer " + main.settings.agent_token}


def _sandbox(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(main.settings, "workspace_roots", [tmp_path.resolve()])
    monkeypatch.setattr(main.settings, "state_db_path", tmp_path / "agent.db")
    return tmp_path


def test_apply_patch_route(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    target = root / "sample.txt"
    target.write_text("alpha\nomega\n", encoding="utf-8")

    client = TestClient(main.app)
    resp = client.post(
        "/v1/project/apply_patch",
        headers=AUTH,
        json={
            "path": str(root),
            "file_path": "sample.txt",
            "operations": [
                {"search_text": "alpha\n", "replace_text": "beta\n", "expected_occurrences": 1},
                {"search_text": "omega\n", "replace_text": "theta\n", "expected_occurrences": 1},
            ],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["patch"]["operation_count"] == 2
    assert target.read_text("utf-8") == "beta\ntheta\n"


def test_multi_file_patch_and_verify_route(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    (root / "a.txt").write_text("red\nblue\n", encoding="utf-8")
    (root / "b.txt").write_text("one\ntwo\n", encoding="utf-8")

    client = TestClient(main.app)
    resp = client.post(
        "/v1/project/multi_file_patch_and_verify",
        headers=AUTH,
        json={
            "path": str(root),
            "patches": [
                {
                    "file_path": "a.txt",
                    "operations": [{"search_text": "red\n", "replace_text": "green\n", "expected_occurrences": 1}],
                },
                {
                    "file_path": "b.txt",
                    "operations": [{"search_text": "one\n", "replace_text": "three\n", "expected_occurrences": 1}],
                },
            ],
            "verify_argv": [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; a=Path('a.txt').read_text(); b=Path('b.txt').read_text(); sys.exit(0 if ('green' in a and 'three' in b) else 1)",
            ],
            "verify_cwd": str(root),
            "verify_timeout_sec": 20,
            "rollback_on_failure": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert len(payload["patches"]) == 2
    assert payload["verify"]["ok"] is True
    assert (root / "a.txt").read_text("utf-8") == "green\nblue\n"
    assert (root / "b.txt").read_text("utf-8") == "three\ntwo\n"


def test_run_test_route_autodetects_pytest(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    client = TestClient(main.app)
    resp = client.post(
        "/v1/project/run_test",
        headers=AUTH,
        json={
            "path": str(root),
            "test_target": "tests/test_sample.py",
            "timeout_sec": 60,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["strategy"] == "python-pytest"
    assert payload["result"]["returncode"] == 0


def test_ensure_memory_route_compacts_jsonl_snapshot(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    client = TestClient(main.app)

    resp = client.post(
        "/v1/project/ensure_memory",
        headers=AUTH,
        json={"path": str(root), "project_name": "tmp-project"},
    )
    assert resp.status_code == 200

    mem = root / ".ai_context" / "sessions.jsonl"
    mem.write_text(''.join([f'{{"idx": {i}}}\n' for i in range(9)]), encoding='utf-8')

    resp = client.post(
        "/v1/project/get_memory_snapshot",
        headers=AUTH,
        json={"path": str(root)},
    )
    assert resp.status_code == 200
    summary = resp.json()["snapshot"]["sessions.jsonl"]
    assert summary["type"] == "jsonl"
    assert summary["line_count"] == 9
    assert len(summary["tail"]) == 5


def test_ssh_exec_allows_ip_from_cidr_with_known_hosts(monkeypatch, tmp_path: Path) -> None:
    _sandbox(monkeypatch, tmp_path)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("dummy host key\n", encoding="utf-8")
    monkeypatch.setattr(main.settings, "ssh_allowed_hosts", [])
    monkeypatch.setattr(main.settings, "ssh_allowed_cidrs", ["192.0.2.0/24"])
    monkeypatch.setattr(main.settings, "ssh_known_hosts_path", str(known_hosts))

    class _Stream:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
        def read(self) -> bytes:
            return self._payload

    class FakeSSHClient:
        def __init__(self) -> None:
            self._host_keys = {}
        def load_system_host_keys(self) -> None:
            pass
        def load_host_keys(self, path: str) -> None:
            self._host_keys[path] = True
        def get_host_keys(self):
            return self._host_keys
        def set_missing_host_key_policy(self, policy) -> None:
            self.policy = policy
        def connect(self, host: str, port: int, username: str, password: str | None, timeout: int) -> None:
            self.connected = (host, port, username, password, timeout)
        def exec_command(self, command: str, timeout: int):
            return None, _Stream(b"ok stdout"), _Stream(b"")
        def close(self) -> None:
            pass

    class FakeParamiko:
        SSHClient = FakeSSHClient
        class RejectPolicy:
            pass

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "paramiko", FakeParamiko)

    client = TestClient(main.app)
    resp = client.post(
        "/v1/ssh/exec",
        headers=AUTH,
        json={
            "host": "192.0.2.55",
            "username": "tester",
            "password": "secret",
            "command": "echo ok",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["stdout"] == "ok stdout"


def test_record_session_auto_generates_session_id(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    client = TestClient(main.app)
    resp = client.post(
        "/v1/project/record_session",
        headers=AUTH,
        json={
            "path": str(root),
            "agent_name": "tester",
            "user_goal": "check ids",
            "summary": "done",
            "result": "ok",
            "next_step": "next",
        },
    )
    assert resp.status_code == 200
    session_id = resp.json()["session"]["session_id"]
    assert isinstance(session_id, str)
    assert session_id.startswith("session-")


def test_record_session_auto_generated_ids_do_not_collide(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    client = TestClient(main.app)
    first = client.post(
        "/v1/project/record_session",
        headers=AUTH,
        json={
            "path": str(root),
            "agent_name": "tester",
            "user_goal": "first",
            "summary": "done",
            "result": "ok",
            "next_step": "next",
        },
    )
    second = client.post(
        "/v1/project/record_session",
        headers=AUTH,
        json={
            "path": str(root),
            "agent_name": "tester",
            "user_goal": "second",
            "summary": "done",
            "result": "ok",
            "next_step": "next",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session"]["session_id"] != second.json()["session"]["session_id"]


def test_finalize_work_generates_change_id(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    client = TestClient(main.app)
    resp = client.post(
        "/v1/project/finalize_work",
        headers=AUTH,
        json={
            "path": str(root),
            "agent_name": "tester",
            "user_goal": "finalize",
            "summary": "done",
            "result": "ok",
            "next_step": "next",
            "change": {"kind": "fix", "reason": "test", "status": "verified"},
            "handoff": {
                "current_state": "good",
                "last_verified_step": "step",
                "next_suggested_step": "next",
            },
            "active_tasks": {"next_resume_hint": "resume"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["session"]["session_id"].startswith("session-")
    change_log = (root / ".ai_context" / "change_log.jsonl").read_text("utf-8").strip().splitlines()
    payload = json.loads(change_log[-1])
    assert payload["change_id"].startswith("change-")
    assert payload["session_id"].startswith("session-")


def test_write_file_respects_max_file_bytes(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "max_file_bytes", 8)
    client = TestClient(main.app)
    resp = client.post(
        "/v1/workspace/write_file",
        headers=AUTH,
        json={"path": str(root / "big.txt"), "content": "123456789"},
    )
    assert resp.status_code == 413
    assert "file too large" in resp.json()["detail"]


def test_finalize_work_openapi_response_schema_has_session_id() -> None:
    schema = main.app.openapi()
    response_schema = schema["paths"]["/v1/project/finalize_work"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    finalize_name = response_schema["$ref"].split("/")[-1]
    session_ref = schema["components"]["schemas"][finalize_name]["properties"]["session"]["$ref"]
    session_name = session_ref.split("/")[-1]
    session_id_schema = schema["components"]["schemas"][session_name]["properties"]["session_id"]
    assert session_id_schema["type"] == "string"


def test_exported_openapi_finalize_work_response_schema_has_session_id() -> None:
    spec = yaml.safe_load((main.PROJECT_DIR / "openapi.gpts.yaml").read_text("utf-8"))
    response_schema = spec["paths"]["/v1/project/finalize_work"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    finalize_name = response_schema["$ref"].split("/")[-1]
    session_ref = spec["components"]["schemas"][finalize_name]["properties"]["session"]["$ref"]
    session_name = session_ref.split("/")[-1]
    session_id_schema = spec["components"]["schemas"][session_name]["properties"]["session_id"]
    assert session_id_schema["type"] == "string"


def test_exported_gpts_openapi_paths_exist_in_backend_openapi() -> None:
    exported = yaml.safe_load((main.PROJECT_DIR / "openapi.gpts.yaml").read_text("utf-8"))
    backend = main.app.openapi()
    for path, methods in exported["paths"].items():
        assert path in backend["paths"], f"missing backend path for exported action route: {path}"
        for method in methods:
            assert method in backend["paths"][path], f"missing backend method for exported action route: {method.upper()} {path}"


def test_exported_gpts_operation_ids_match_backend_openapi() -> None:
    exported = yaml.safe_load((main.PROJECT_DIR / "openapi.gpts.yaml").read_text("utf-8"))
    backend = main.app.openapi()
    for path, methods in exported["paths"].items():
        for method, spec in methods.items():
            exported_operation = spec.get("operationId")
            backend_operation = backend["paths"][path][method].get("operationId")
            assert exported_operation == backend_operation, (
                f"operationId mismatch for {method.upper()} {path}: "
                f"exported={exported_operation!r}, backend={backend_operation!r}"
            )


def test_search_text_parses_windows_drive_letter_paths(monkeypatch, tmp_path: Path) -> None:
    class Completed:
        stdout = "C:\\\\Projects\\\\demo\\\\app.py:12:print('hello')\n"

    def fake_run(*args, **kwargs):
        return Completed()

    monkeypatch.setattr(core_utils.shutil, "which", lambda name: "rg" if name == "rg" else None)
    monkeypatch.setattr(core_utils.subprocess, "run", fake_run)
    results = core_utils.search_text(tmp_path, "hello", max_results=10)
    assert results == [{"path": r"C:\\Projects\\demo\\app.py", "line": 12, "snippet": "print('hello')"}]


def test_get_command_logs_returns_live_buffered_output(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    client = TestClient(main.app)
    start = client.post(
        "/v1/exec/start",
        headers=AUTH,
        json={
            "argv": [
                sys.executable,
                "-c",
                "import sys,time; print('hello', flush=True); time.sleep(2)",
            ],
            "cwd": str(root),
        },
    )
    assert start.status_code == 200
    process_id = start.json()["process_id"]
    time.sleep(0.25)
    t0 = time.monotonic()
    logs = client.post(
        "/v1/exec/logs",
        headers=AUTH,
        json={"process_id": process_id, "max_chars": 1000},
    )
    elapsed = time.monotonic() - t0
    assert logs.status_code == 200
    assert elapsed < 1.0
    assert "hello" in logs.json()["logs"]
    client.post("/v1/exec/stop", headers=AUTH, json={"process_id": process_id})


def test_run_service_and_smoke_check_detects_startup_text(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    client = TestClient(main.app)
    resp = client.post(
        "/v1/project/run_service_and_smoke_check",
        headers=AUTH,
        json={
            "path": str(root),
            "service_argv": [
                sys.executable,
                "-u",
                "-c",
                "import time; print('SERVER READY', flush=True); time.sleep(1.5)",
            ],
            "smoke_argv": [sys.executable, "-c", "print('smoke ok')"],
            "startup_text": "SERVER READY",
            "startup_timeout_sec": 5,
            "smoke_timeout_sec": 10,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["started"] is True
    assert payload["smoke"]["ok"] is True
    assert "SERVER READY" in "\n".join(payload["service_output"])


def test_start_command_returns_controlled_error_for_missing_binary(monkeypatch, tmp_path: Path) -> None:
    root = _sandbox(monkeypatch, tmp_path)
    client = TestClient(main.app)
    resp = client.post(
        "/v1/exec/start",
        headers=AUTH,
        json={"argv": ["definitely-not-a-real-command-xyz"], "cwd": str(root)},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["command_not_found"] is True
    assert "command not found" in payload["output"]


def test_ssh_exec_rejects_when_no_known_hosts_loaded(monkeypatch, tmp_path: Path) -> None:
    _sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(main.settings, "ssh_allowed_hosts", ["192.0.2.122"])
    monkeypatch.setattr(main.settings, "ssh_allowed_cidrs", [])
    monkeypatch.setattr(main.settings, "ssh_known_hosts_path", str(tmp_path / "missing_known_hosts"))

    class FakeSSHClient:
        def load_system_host_keys(self) -> None:
            pass
        def load_host_keys(self, path: str) -> None:
            pass
        def get_host_keys(self):
            return {}
        def set_missing_host_key_policy(self, policy) -> None:
            pass
        def connect(self, *args, **kwargs) -> None:
            raise AssertionError("connect should not be reached without known_hosts")
        def close(self) -> None:
            pass

    class FakeParamiko:
        SSHClient = FakeSSHClient
        class RejectPolicy:
            pass

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "paramiko", FakeParamiko)

    client = TestClient(main.app)
    resp = client.post(
        "/v1/ssh/exec",
        headers=AUTH,
        json={
            "host": "192.0.2.122",
            "username": "tester",
            "password": "secret",
            "command": "echo ok",
        },
    )
    assert resp.status_code == 500
    assert "known_hosts" in resp.json()["detail"]
