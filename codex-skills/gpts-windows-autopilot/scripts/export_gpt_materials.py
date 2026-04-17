#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_branch_root  # noqa: E402


def first_openapi_url(openapi_path: Path):
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
    instructions_path = branch_root / "gpts" / "system_instructions.txt"
    knowledge_root = branch_root / "gpts" / "knowledge"
    openapi_path = branch_root / "openapi.gpts.yaml"

    knowledge_files = sorted(str(path) for path in knowledge_root.rglob("*.md"))
    instructions_text = instructions_path.read_text(encoding="utf-8") if instructions_path.exists() else ""

    output = {
        "instructions": {
            "path": str(instructions_path),
            "exists": instructions_path.exists(),
            "chars": len(instructions_text),
            "preview": instructions_text[:500],
        },
        "knowledge": {
            "root": str(knowledge_root),
            "count": len(knowledge_files),
            "files": knowledge_files,
        },
        "actions": {
            "openapi_path": str(openapi_path),
            "exists": openapi_path.exists(),
            "server_url": first_openapi_url(openapi_path) if openapi_path.exists() else None,
        },
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
