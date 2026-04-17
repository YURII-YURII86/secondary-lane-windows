# Verification Checklist

Do not declare success until every item below is factually true.

## Local machine checks

- project folder exists
- `.env` exists
- `AGENT_TOKEN` is not empty
- `NGROK_DOMAIN` is not empty
- `WORKSPACE_ROOTS` begins with the real project folder
- `py -3.13 --version` works
- `ngrok version` works

## Panel and tunnel checks

- the project panel opened (the "Запустить GPTS Agent.bat" console window stays open)
- the agent process is running and its `/health` or `/capabilities` endpoint responds
- ngrok tunnel is active
- a real public `https://...` URL is visible
- the port was not unsafely reused from an unknown process

## OpenAPI checks

- `openapi.gpts.yaml` exists
- `servers -> url` contains the real public URL
- the placeholder URL is gone

## GPT builder checks

- GPT editor is open
- `Instructions` received the system instructions text
- `Knowledge` received the intended knowledge files
- `Actions` accepted the schema
- auth token was accepted

## Action-call checks

- preview can call a simple action
- saved GPT can call a simple action
- no auth error appears
- panel remains open during the test

## Handoff checks

- user knows where the project folder is
- user knows how to relaunch the panel
- user knows the panel must stay open during use
- user knows the first place to check if GPT stops reaching the agent
