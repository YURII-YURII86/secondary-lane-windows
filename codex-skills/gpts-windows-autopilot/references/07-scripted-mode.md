# Scripted Mode

Use the bundled scripts first when they match the task.

These scripts make the flow more seamless for the user because they reduce manual file inspection and repetitive editing.

## Scripts

### `scripts/inspect_windows_gpts.py`

Use this first.

Purpose:

- inspect the Windows branch
- check important files
- inspect `.env`
- inspect `openapi.gpts.yaml`
- test `py -3.13`
- test `ngrok`

Note:

- this script inspects the current host environment;
- if it is run on macOS or Linux, command checks describe that host, not a real target Windows PC.

Typical call:

```bash
python scripts/inspect_windows_gpts.py "<workspace-or-branch-root>"
```

### `scripts/discover_secondarylane_layout.py`

Use this when the expected project folder or Windows branch name may have changed.

Purpose:

- scan for likely SecondaryLane Windows roots
- score candidate folders by marker files
- return the strongest match first

Typical call:

```bash
python scripts/discover_secondarylane_layout.py "<search-root>"
```

### `scripts/discover_secondarylane_artifacts.py`

Use this when the branch root is known, but important internal files may have moved or changed names.

Purpose:

- recover the best candidate for launcher
- recover the best candidate for OpenAPI schema
- recover the best candidate for system instructions
- recover the best candidate for knowledge root
- recover the best candidate for `.env.example`

Typical call:

```bash
python scripts/discover_secondarylane_artifacts.py "<branch-root>"
```

### `scripts/build_env.py`

Use this when the real `ngrok` domain is known and `.env` is missing or incomplete.

Purpose:

- create `.env` from `.env.example` if needed
- generate `AGENT_TOKEN`
- write `NGROK_DOMAIN`
- write `WORKSPACE_ROOTS`
- update path-based settings to the real project path

Important:

- on non-Windows hosts, always pass `--workspace-root` with the real future Windows path such as `C:\SecondLane`;
- otherwise the script must stop instead of silently writing a broken path.

### `scripts/inspect_windows_host.ps1`

Use this on the real Windows machine when available.

Purpose:

- inspect the actual Windows host
- verify `py -3.13`
- verify `ngrok`
- verify `.env`
- verify `openapi.gpts.yaml`
- verify whether `WORKSPACE_ROOTS` starts with the real branch path

Typical call:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\inspect_windows_host.ps1 "C:\SecondLane"
```

Typical call for `build_env.py`:

```bash
python scripts/build_env.py "<workspace-or-branch-root>" --ngrok-domain "demo-team.ngrok.app"
```

### `scripts/export_gpt_materials.py`

Use this before the GPT builder step.

Purpose:

- show where `Instructions` text comes from
- list all `Knowledge` files
- show the OpenAPI file and current server URL

Typical call:

```bash
python scripts/export_gpt_materials.py "<workspace-or-branch-root>"
```

### `scripts/open_setup_pages.py`

Use this to open official pages quickly when browser control is limited.

Examples:

Available page keys (pass any combination):

- `python-windows` — Python download page
- `ngrok-signup` — ngrok sign-up page (for brand-new users)
- `ngrok-download` — ngrok CLI download
- `ngrok-authtoken` — authtoken page after login
- `ngrok-domains` — reserved domains page
- `chatgpt-gpts` — user's GPT list
- `chatgpt-editor` — new-GPT editor
- `openai-gpts-help` — OpenAPI Actions help article

Examples:

```bash
python scripts/open_setup_pages.py python-windows
python scripts/open_setup_pages.py ngrok-signup ngrok-authtoken ngrok-domains
python scripts/open_setup_pages.py chatgpt-editor
```

## Rule

If one of these scripts can replace tedious manual checking, prefer the script.
If the task has moved onto a real Windows PC, prefer the PowerShell inspection script over host-side guesses.
