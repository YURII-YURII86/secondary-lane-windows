#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_branch_root  # noqa: E402


IMPORTANT_FILES = [
    ".env.example",
    ".env",
    "openapi.gpts.yaml",
    "gpts/system_instructions.txt",
    "Запустить GPTS Agent.bat",
    "gpts_agent_control.py",
]


def run_command(command):
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }


def parse_env(env_path: Path):
    if not env_path.exists():
        return {}
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def first_openapi_url(openapi_path: Path):
    if not openapi_path.exists():
        return None
    for line in openapi_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- url:"):
            return stripped.split(":", 1)[1].strip()
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", help="Workspace root or Windows branch root")
    args = parser.parse_args()

    branch_root = find_branch_root(Path(args.project_root).expanduser().resolve())
    env_values = parse_env(branch_root / ".env")
    openapi_url = first_openapi_url(branch_root / "openapi.gpts.yaml")
    knowledge_root = branch_root / "gpts" / "knowledge"

    files = {}
    for relative_path in IMPORTANT_FILES:
        path = branch_root / relative_path
        files[relative_path] = {
            "exists": path.exists(),
            "path": str(path),
        }

    knowledge_files = sorted(
        str(path) for path in knowledge_root.rglob("*.md")
    ) if knowledge_root.exists() else []

    output = {
        "host_platform": sys.platform,
        "branch_root": str(branch_root),
        "important_files": files,
        "env": {
            "exists": (branch_root / ".env").exists(),
            "agent_token_present": bool(env_values.get("AGENT_TOKEN")),
            "agent_token_placeholder": env_values.get("AGENT_TOKEN", "").startswith("replace-this"),
            "ngrok_domain": env_values.get("NGROK_DOMAIN", ""),
            "workspace_roots": env_values.get("WORKSPACE_ROOTS", ""),
            "first_workspace_root": env_values.get("WORKSPACE_ROOTS", "").split(";", 1)[0] if env_values.get("WORKSPACE_ROOTS") else "",
            "workspace_root_looks_windows": bool(env_values.get("WORKSPACE_ROOTS")) and len(env_values.get("WORKSPACE_ROOTS", "")) >= 3 and env_values.get("WORKSPACE_ROOTS", "")[1:3] == ":\\",
        },
        "openapi": {
            "path": str(branch_root / "openapi.gpts.yaml"),
            "server_url": openapi_url,
            "has_real_url": bool(openapi_url and "your-domain" not in openapi_url),
        },
        "knowledge": {
            "root": str(knowledge_root),
            "count": len(knowledge_files),
            "files": knowledge_files,
        },
        "commands": {
            "py_3_13": run_command(["py", "-3.13", "--version"]),
            "python": run_command(["python", "--version"]),
            "ngrok": run_command(["ngrok", "version"]),
        },
        "warnings": [],
    }

    if not sys.platform.startswith("win"):
        output["warnings"].append(
            "This inspection is running on a non-Windows host, so command results describe the current host, not a target Windows PC."
        )
    first_root = output["env"]["first_workspace_root"]
    if first_root and not output["env"]["workspace_root_looks_windows"]:
        output["warnings"].append(
            "WORKSPACE_ROOTS does not start with a Windows-style path. This is unsafe for a real Windows deployment."
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
