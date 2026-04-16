# Second Lane | Версия для Windows

**Вторая полоса для твоего вайбкодинга.**

Second Lane gives ChatGPT real actions on your machine: inspect code, patch files, run tests, start services, verify results, and keep project memory between sessions.

**It is especially strong when Claude Code, Codex, or another coding agent hits limits, loses context, or just becomes inconvenient.**

Built on official ChatGPT features: GPTs, Actions, instructions, and knowledge.

Built by [Yurii Slepnev](https://t.me/yurii_yurii86) · [YouTube](https://youtube.com/@yurii_yurii86) · [Instagram](https://instagram.com/yurii_yurii86) · Apache-2.0

[Русская версия](docs/README_RU.md)

---

## Demo

See the Windows version in action before you read the setup:

<p align="center">
  <img src="assets/demo/secondary-lane-demo.gif" alt="Second Lane Windows demo" width="100%">
</p>

## Screenshots

<p align="center">
  <img src="assets/screenshots/chat-view-showcase.png" alt="Second Lane chat workflow" width="49%">
  <img src="assets/screenshots/main-interface-showcase.png" alt="Second Lane control panel and local runtime" width="49%">
</p>

<p align="center">
  <sub><strong>Chat-driven workflow</strong> · The task moves inside the normal ChatGPT interface</sub>
  <br>
  <sub><strong>Control panel and local runtime</strong> · ChatGPT on one side, local execution layer on the other</sub>
</p>

## Strongest Use Case

Second Lane is not just "ChatGPT that can read files".

Its strongest job is to give you a second working lane when Claude Code, Codex, or another agent stalls:

- **Continue after limits** instead of waiting for the next quota reset
- **Pick up work after context loss** without restarting everything from zero
- **Run real local actions through ChatGPT**: inspect, patch, run, verify
- **Keep project memory between sessions** through `.ai_context/`
- **Work from the normal ChatGPT interface** instead of a CLI-first flow

## Why People Use It

Second Lane is for people who already like ChatGPT, but want it to do real work on a real project.

- **No extra API-key workflow.** If you already pay for ChatGPT Plus, you can use Custom GPTs + Actions instead of setting up separate model billing.
- **Local by design.** Second Lane runs on your machine and only works inside folders you explicitly allow.
- **Works from the ChatGPT app too.** With `ngrok`, your GPT can reach your machine from your phone, laptop, or anywhere else.
- **Works across languages and stacks.** Python, Node, Go, Rust, Java, scripts, monorepos — if your machine can run the right command, ChatGPT can operate it.
- **ChatGPT instead of a CLI.** You work through the normal ChatGPT interface, not a terminal-first tool.

## Built on Official ChatGPT Features

Second Lane works through the normal ChatGPT workflow: Custom GPTs, Actions, instructions, and knowledge files.

- **No hidden API tricks.** You connect a GPT to your local server through standard Actions.
- **No stolen keys or gray schemes.** You use your own ChatGPT account and the product features that already exist.
- **No unofficial access layer.** Second Lane does not replace ChatGPT. It extends it with a local execution runtime on your machine.

## What It Is

Second Lane is a local server that connects ChatGPT to your project through GPT Actions.

It lets ChatGPT:

- **Read and search** your project files
- **Patch code** with automatic rollback on verification failure
- **Run tests** with auto-detection (`pytest`, `npm test`, `make test`)
- **Start services** and run smoke checks
- **Execute commands** in your workspace
- **Keep project memory** across sessions via `.ai_context/`

```text
Your machine                          ChatGPT
┌─────────────────┐    ngrok     ┌──────────────┐
│  Second Lane    │◄────────────►│  GPT Actions │
│  localhost:8787 │   tunnel     │  Custom GPT  │
└─────────────────┘              └──────────────┘
```

## Why It Feels Different

Most tools in this space are terminal-first and API-key-first. Second Lane is built around a different idea:

- **Use ChatGPT as the interface**
- **Run everything locally**
- **Keep the project close to the machine**
- **Make remote control simple enough to use from a phone**

That makes it useful not only as a backup when another agent hits a limit, but as a primary workflow for many people.

## Common Use Cases

- **Turn ChatGPT into your main coding agent** for local projects
- **Continue after another agent hits limits** or loses context
- **Work on a project from your phone** through the ChatGPT app
- **Keep code local** for privacy, client work, or internal tools
- **Use ChatGPT on stacks that are not tied to one editor**
- **Help students learn on real projects** with an interface they already know
- **Give a team one familiar UI** instead of teaching everyone a CLI-heavy workflow

## Second Lane vs Alternatives

| Feature | Open Interpreter / Aider style tools | Second Lane |
| --- | --- | --- |
| Main interface | CLI | ChatGPT UI |
| Typical setup | Separate API keys and model billing | ChatGPT Plus + local server |
| Runs on your machine | Yes | Yes |
| Mobile access through ChatGPT app | Usually no | Yes |
| Project memory between sessions | Partial / tool-specific | Built-in `.ai_context/` |
| Works across languages and stacks | Yes | Yes |
| Best fit | Terminal-native developers | People who want ChatGPT to operate projects directly |

## Quick Start (Windows)

```powershell
Copy-Item .env.example .env
# Set AGENT_TOKEN (long random secret)
# Set NGROK_DOMAIN (free domain from dashboard.ngrok.com)
py -3.13 gpts_agent_control.py
```

Or double-click `Запустить GPTS Agent.bat`.

Step-by-step guide for beginners: [docs/WINDOWS_FIRST_START.md](docs/WINDOWS_FIRST_START.md)

### Manual environment setup

```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Connect Your GPT

1. Import `openapi.gpts.yaml` into GPT Actions
2. Set bearer token from `.env`
3. Paste `gpts/system_instructions.txt` into GPT instructions
4. Upload `gpts/knowledge/` into GPT knowledge
5. Test: `getCapabilities` → `inspectProject` → `runTest`

## What GPT Can Actually Do

| Action | What it does |
| --- | --- |
| `inspectProject` | Scan project structure, detect type, find key files |
| `readFile` / `writeFile` | Read and write files in your workspace |
| `searchWorkspace` | Full-text search across project files |
| `applyPatch` | Multi-step safe patching with checkpoint |
| `safePatchAndVerifyProjectFile` | Patch → verify → auto-rollback on failure |
| `multiFilePatchAndVerify` | Coordinated patches across multiple files |
| `runTest` | Auto-detect and run tests (`pytest`, `npm`, `make`) |
| `runProjectServiceAndSmokeCheck` | Start service, wait for ready, smoke check, stop |
| `analyzeProjectBuildFailure` | Run build command and classify failure type |
| `runCommand` / `startCommand` | Execute any command in workspace |
| `gitStatus` / `gitDiff` | Git operations |
| `finalizeProjectWork` | Save session, handoff, and project state |

## Project Structure

```text
app/main.py              # FastAPI server — all API routes
app/core/                # Config, security, utils, project memory
gpts/                    # GPT system instructions + knowledge pack
gpts_agent_control.py    # Control panel (daemon + ngrok tunnel)
openapi.gpts.yaml        # Curated OpenAPI schema for GPT Actions
tests/                   # Regression and smoke tests
.env.example             # Configuration template
```

## Security

- All routes require bearer token authentication
- File access is restricted to `WORKSPACE_ROOTS`
- SSH is restricted to allowlisted hosts/CIDRs with `known_hosts` + `RejectPolicy`
- Weak tokens are rejected at startup (minimum 24 characters)
- Key actions are logged to an SQLite audit trail

## Local Verification

```powershell
# Full verify (compile + tests)
powershell -ExecutionPolicy Bypass -File scripts\verify_local.ps1

# Tests only
powershell -ExecutionPolicy Bypass -File scripts\run_local_pytest.ps1

# Runtime smoke check (starts server, checks health, stops)
powershell -ExecutionPolicy Bypass -File scripts\smoke_local.ps1
```

## Requirements

- Python 3.13
- ngrok (free tier works)
- ChatGPT Plus or another ChatGPT plan with GPTs + Actions support

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
