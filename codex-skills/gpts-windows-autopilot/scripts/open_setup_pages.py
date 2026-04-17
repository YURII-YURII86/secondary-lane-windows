#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys


PAGES = {
    "python-windows": "https://www.python.org/downloads/windows/",
    "ngrok-signup": "https://dashboard.ngrok.com/signup",
    "ngrok-download": "https://ngrok.com/download",
    "ngrok-authtoken": "https://dashboard.ngrok.com/get-started/your-authtoken",
    "ngrok-domains": "https://dashboard.ngrok.com/domains",
    "chatgpt-gpts": "https://chatgpt.com/gpts",
    "chatgpt-editor": "https://chatgpt.com/gpts/editor",
    "openai-gpts-help": "https://help.openai.com/en/articles/8554397-creating-a-gpt",
}


def open_url(url):
    if sys.platform == "darwin":
        command = ["open", url]
    elif sys.platform.startswith("win"):
        command = ["cmd", "/c", "start", "", url]
    else:
        command = ["xdg-open", url]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stderr": (completed.stderr or "").strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("page", nargs="+", choices=sorted(PAGES.keys()))
    args = parser.parse_args()

    result = {}
    for page in args.page:
        url = PAGES[page]
        result[page] = {
            "url": url,
            "open_result": open_url(url),
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
