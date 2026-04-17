# State Machine

Use this as the run-control table.

The agent should always know which state it is in before acting.

| State | Real-world condition | Agent action | Required verification | Next |
|---|---|---|---|---|
| S0 | Current setup state unknown | Inspect project files and available commands | Real state of project, Python, ngrok, `.env`, panel, OpenAPI known | S1-S7 |
| S1 | Project path not confirmed | Confirm or prepare Windows project folder | Folder exists and contains launcher, `.env.example`, OpenAPI | S2 |
| S2 | Python 3.13 unknown or missing | Check and if needed guide install | `py -3.13 --version` works | S3 |
| S3 | ngrok unknown or missing | Check and if needed guide install | `ngrok version` works | S4 |
| S4 | ngrok account steps unfinished | Open registration/login/token/domain path and wait only for human gate | Real token/domain become available | S5 |
| S5 | `.env` absent or incomplete | Create or update `.env` | `.env` contains valid `AGENT_TOKEN`, `NGROK_DOMAIN`, `WORKSPACE_ROOTS` | S6 |
| S6 | Panel not running | Launch the project panel | Panel opens, daemon healthy, tunnel starts | S7 |
| S7 | Tunnel/OpenAPI unverified | Verify public URL and `openapi.gpts.yaml` | Real public URL exists and YAML contains it | S8 |
| S8 | GPT builder materials not prepared | Open exact files and map what goes where | Instructions, Knowledge, Actions source files ready | S9 |
| S9 | ChatGPT gate unfinished | Open GPT editor and wait only for login/plan gate | GPT editor reachable | S10 |
| S10 | GPT not yet assembled | Guide exact GPT creation flow | GPT fields and Actions configured | S11 |
| S11 | Auth or action call unverified | Fix auth and test Preview | Preview action call works | S12 |
| S12 | Final user-facing GPT unverified | Test one simple real call in saved GPT | Saved GPT can call the agent | S13 |
| S13 | Final handoff to user | Give plain-language summary: project folder, `.env` location, what stays open, how to relaunch, what to do if tunnel dies | User confirms they understand and can reopen next time | DONE |

## Stop rule

If the agent cannot honestly answer:

- `what state am I in right now?`

it must stop and re-read reality before acting again.

## Resume rule

After interruption:

- locate the actual current state
- resume from that state
- do not replay already verified steps
