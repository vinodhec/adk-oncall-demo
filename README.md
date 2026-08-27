# ADK On-Call Triage Demo

An on-call incident triage agent built with [Google ADK](https://google.github.io/adk-docs/), in two flavours: a single agent with three tools, and the same three tools split across a multi-agent team.

> **All data is mocked.** The three tools return values from hardcoded Python dicts. There is no Jira, no GitHub, no network calls, and nothing is written anywhere. Safe to run and safe to break.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then add your key
```

Get a free API key at [aistudio.google.com](https://aistudio.google.com).

## Run

```bash
adk web
```

Run it from the repo root, open the URL it prints, and pick either `oncall_agent` (single agent) or `oncall_team` (coordinator + sub-agents) from the dropdown in the UI.

## Try these prompts

| Prompt | What it shows |
| --- | --- |
| `What did we deploy to payments?` | One tool call — `get_recent_deployments` |
| `Show me recent errors on payments` | A different tool — `fetch_error_logs` |
| `What did we deploy to billing?` | The error path — no records for `billing`, so the tool returns `status: "error"` and the agent says so instead of inventing an answer |
| `Payments is failing in prod - check if we deployed recently, look at the error logs, and file a high-severity ticket if it's broken` | All three tools, chained in order — deploys, logs, then the ticket |
| `Who's on call this weekend?` | No tool at all — nothing in the toolset answers this, so the model just replies |

In `oncall_team`, that fourth prompt also shows routing: the coordinator hands off to `diagnostics_agent` first, then to `ticketing_agent`.

## How it works

The model never runs your code. It reads the function signature and docstring, decides a tool is needed, and emits a request naming the function and its arguments. ADK is what actually calls the Python function, and feeds the return value back into the conversation as the next turn. The model then keeps going with that result in hand.

Two consequences worth pointing at during the demo:

- **Docstrings are the API.** The docstring and type hints are the only description the model gets, so they are prompt text, not documentation.
- **Descriptions drive routing.** In `oncall_team`, the coordinator picks a sub-agent by reading each one's `description` field. Change the wording, change the routing.

## Licence

MIT
