# Secondary LANE | Windows Version

**A second lane for your vibe coding.**

Secondary LANE gives ChatGPT real actions on your machine: inspect code, patch files, run tests, start services, verify results, and keep project context between sessions.

**It is especially useful when Claude Code, Codex, or another coding agent hits limits, loses context, or simply becomes inconvenient.**

Built on official ChatGPT features: GPTs, Actions, instructions, and knowledge files.

Built by [Yurii Slepnev](https://t.me/yurii_yurii86) · [YouTube](https://youtube.com/@yurii_yurii86) · [Instagram](https://instagram.com/yurii_yurii86) · Apache-2.0

Russian setup guide: [docs/WINDOWS_FIRST_START.md](docs/WINDOWS_FIRST_START.md)

---

## Demo

See the Windows version in action before reading the setup guide:

<p align="center">
  <img src="assets/demo/secondary-lane-demo.gif" alt="Secondary LANE Windows demo" width="100%">
</p>

## Screenshots

<p align="center">
  <img src="assets/screenshots/chat-view-showcase.png" alt="Secondary LANE chat workflow" width="49%">
  <img src="assets/screenshots/main-interface-showcase.png" alt="Secondary LANE control panel and local runtime" width="49%">
</p>

<p align="center">
  <sub><strong>Chat-driven workflow</strong> · The task moves inside the normal ChatGPT interface</sub>
  <br>
  <sub><strong>Control panel and local runtime</strong> · ChatGPT on one side, local execution layer on the other</sub>
</p>

## Strongest Use Case

Secondary LANE is not just "ChatGPT that can read files."

Its strongest job is to give you a second working lane when Claude Code, Codex, or another agent stalls:

- **Continue after limits** instead of waiting for the next quota reset
- **Pick up work after context loss** without restarting everything from zero
- **Run real local actions through ChatGPT**: inspect, patch, run, verify
- **Keep project memory between sessions** through `.ai_context/`
- **Work from the normal ChatGPT interface** instead of a CLI-first flow

## Why People Use It

Secondary LANE is for people who already like ChatGPT, but want it to do real work on a real project.

- **No extra API-key workflow.** If you already pay for ChatGPT Plus or another plan with GPTs and Actions, you do not need a separate model billing setup.
- **Local by design.** Secondary LANE runs on your machine and only works inside folders you explicitly allow.
- **Works from the ChatGPT app too.** With `ngrok`, your GPT can reach your machine from your phone, laptop, or anywhere else.
- **Works across languages and stacks.** Python, Node, Go, Rust, Java, scripts, monorepos — if your machine can run the right command, ChatGPT can operate it.
- **ChatGPT instead of a CLI.** You work through the normal ChatGPT interface, not a terminal-first tool.

## Built on Official ChatGPT Features

Secondary LANE works through the normal ChatGPT workflow: Custom GPTs, Actions, instructions, and knowledge files.

- **No hidden API tricks.** You connect a GPT to your local server through standard Actions.
- **No gray schemes or stolen keys.** You use your own ChatGPT account and the product features that already exist.
- **No unofficial access layer.** Secondary LANE does not replace ChatGPT. It extends it with a local execution runtime on your machine.

## What It Is

Secondary LANE is a local server that connects ChatGPT to your project through GPT Actions.

It lets ChatGPT:

- **Read and search** project files
- **Patch code** with automatic rollback if verification fails
- **Run tests** with auto-detection (`pytest`, `npm test`, `make test`)
- **Start services** and run smoke checks
- **Execute commands** in your workspace
- **Keep project memory** across sessions through `.ai_context/`

```text
Your machine                         ChatGPT
┌─────────────────┐    ngrok     ┌──────────────┐
│ Secondary LANE  │◄────────────►│  GPT Actions │
│ localhost:8787  │   tunnel     │  Custom GPT  │
└─────────────────┘              └──────────────┘
```

## Why It Feels Different

Most tools in this category are terminal-first and API-key-first. Secondary LANE is built around a different idea:

- **Use ChatGPT as the main interface**
- **Run everything locally**
- **Keep the project close to the machine**
- **Make remote control simple enough to use even from a phone**

That makes Secondary LANE useful not only as a backup when another agent hits a limit, but also as a primary workflow for many people.

## Common Use Cases

- **Make ChatGPT your main coding agent** for local projects
- **Continue after another agent hits limits** or loses context
- **Work on a project from your phone** through the ChatGPT app
- **Keep code local** for privacy, client work, or internal tools
- **Use ChatGPT on stacks that are not tied to one editor**
- **Help students learn on real projects** with an interface they already know
- **Give a team one familiar UI** instead of teaching everyone CLI-heavy tools

## Secondary LANE vs Alternatives

| Feature | Tools like Open Interpreter / Aider | Secondary LANE |
| --- | --- | --- |
| Main interface | CLI | ChatGPT |
| Typical setup | Separate API keys and model billing | ChatGPT Plus + local server |
| Runs on your machine | Yes | Yes |
| Mobile access through the ChatGPT app | Usually no | Yes |
| Project memory between sessions | Partial or tool-specific | Built-in `.ai_context/` |
| Works across languages and stacks | Yes | Yes |
| Best fit | Terminal-native developers | People who want ChatGPT to operate projects directly |

## Quick Start (Windows)

The easiest path now is:

1. Put the project folder somewhere simple, for example `C:\SecondLane`
2. Double-click `Установить Secondary LANE.bat`
3. Follow the installer window
4. If Python is missing, the installer downloads the official Python 3.13 installer, opens it, and then retries
5. When the installer finishes, it opens the panel for you or leaves a clear `Запустить панель` button

The installer checks Python 3.13, helps with ngrok, creates `.env`, prepares `.venv`, repairs broken local setup, and leaves only the truly human steps to you.

If you prefer another route, here are the options.

Before you start, you still need **three things** available at some point:

1. **Python 3.13** for Windows — [python.org/downloads/windows](https://www.python.org/downloads/windows/) (tick "Add python.exe to PATH")
2. **ngrok** account + a reserved free domain — [dashboard.ngrok.com](https://dashboard.ngrok.com) (free tier is enough)
3. **ChatGPT Plus** (or any plan that supports Custom GPTs with Actions)

Then pick one of two paths.

### Path A — Use the built-in installer

If you want the simplest beginner-friendly route, start here.

1. Double-click `Установить Secondary LANE.bat`
2. If Python is missing, the installer downloads the official Python 3.13 Windows installer and opens it for you
3. If ngrok is missing, the installer tries `winget`, then a direct official ngrok zip download; if Windows still cannot find it, choose `ngrok.exe` in the installer
4. Paste your ngrok authtoken and reserved domain into the installer
5. Let it prepare or repair `.env` and `.venv`
6. Let it open the panel for you, or click `Запустить панель` if Windows asks you to confirm the launch

For a more detailed walkthrough with explanations and screenshots, use:

**[docs/WINDOWS_FIRST_START.md](docs/WINDOWS_FIRST_START.md)**

### Path B — Manual install (no agent needed)

If you prefer doing everything by hand, use the step-by-step beginner guide:

**[docs/WINDOWS_FIRST_START.md](docs/WINDOWS_FIRST_START.md)** — full guide with screenshots and explanations.

Short version if you are comfortable with a terminal:

```powershell
# 1. Create config from template and edit it
Copy-Item .env.example .env
notepad .env
# In .env set AGENT_TOKEN (a long random secret) and NGROK_DOMAIN
# (your reserved domain from dashboard.ngrok.com, without "https://")

# 2. Install dependencies
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 3. Launch the control panel
py -3.13 gpts_agent_control.py
```

Or just **double-click `Установить Secondary LANE.bat`** first — it now prepares the missing setup automatically and then leads you to the panel.

> Generate a strong `AGENT_TOKEN` with:
> `py -3.13 -c "import secrets; print(secrets.token_urlsafe(48))"`

## Connect Your GPT

After the control panel is running and the ngrok tunnel is up:

1. Open ChatGPT → **Create a GPT** → switch to the **Configure** tab
2. **Instructions** — paste contents of [`gpts/system_instructions.txt`](gpts/system_instructions.txt)
3. **Knowledge** — upload every file from [`gpts/knowledge/`](gpts/knowledge/)
4. **Actions** → **Create new action** → paste the content of [`openapi.gpts.yaml`](openapi.gpts.yaml)
5. **Authentication** → type **API Key**, auth type **Bearer**, paste the raw value of `AGENT_TOKEN` from your `.env` (without the word `Bearer`)
6. Run the first checks in preview: `getCapabilities` → `inspectProject` → `runTest`

Step-by-step guide with screenshots: [gpts/ACTIONS_SETUP.md](gpts/ACTIONS_SETUP.md).

## What GPT Can Actually Do Through Secondary LANE

| Action | What it does |
| --- | --- |
| `inspectProject` | Scans the project structure, detects the project type, finds key files |
| `readFile` / `writeFile` | Reads and writes files in your workspace |
| `searchWorkspace` | Searches text across the project |
| `applyPatch` | Performs a safe patch with a checkpoint |
| `safePatchAndVerifyProjectFile` | Patch -> verify -> rollback on failure |
| `multiFilePatchAndVerify` | Coordinates patches across multiple files |
| `runTest` | Automatically chooses and runs tests |
| `runProjectServiceAndSmokeCheck` | Starts a service, waits for readiness, checks it, stops it |
| `analyzeProjectBuildFailure` | Runs a build and helps classify the failure |
| `runCommand` / `startCommand` | Executes arbitrary commands in the project |
| `gitStatus` / `gitDiff` | Basic git operations |
| `finalizeProjectWork` | Saves session state and handoff |

## Project Structure

```text
app/main.py              # FastAPI server and API routes
app/core/                # Config, security, utilities, project memory
gpts/                    # GPT instructions and knowledge pack
gpts_agent_control.py    # Control panel (daemon + ngrok tunnel)
second_lane_installer.py # Guided installer for Windows
openapi.gpts.yaml        # API schema for GPT Actions
.env.example             # Configuration template
```

## Security

- all routes require a bearer token
- file access is restricted by `WORKSPACE_ROOTS`
- SSH is restricted to approved hosts and networks
- weak tokens are rejected at startup
- key actions are written to an SQLite audit log

## Requirements

- **Python 3.13** for Windows. The installer and repair checks intentionally standardize on 3.13 so beginners do not fall into version mismatch problems.
- **`ngrok`** with a free account — create an **authtoken** and a **reserved domain** at [dashboard.ngrok.com](https://dashboard.ngrok.com) before first launch
- **ChatGPT Plus** or any plan that supports Custom GPTs with Actions

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
