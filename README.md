# ADK On-Call Triage Demo

An on-call incident triage agent built with [Google ADK](https://google.github.io/adk-docs/), in two flavours: a single agent with three tools, and the same three tools split across a two-step agent pipeline that passes findings through shared session state.

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

Run it from the repo root, open the URL it prints, and pick an app from the dropdown in the UI:

| App | Shape | What it is for |
| --- | --- | --- |
| `oncall_agent` | one `Agent`, three tools | The live demo. One agent choosing between tools. |
| `oncall_team` | `oncall_lead` + two sub-agents, LLM-routed | The multi-agent clip. Routing shows up as `transfer_to_agent` in the event panel. |
| `oncall_pipeline` | `SequentialAgent` over shared session state | The deterministic alternative, and the shared-state example below. |

## Try these prompts

| Prompt | What it shows |
| --- | --- |
| `What did we deploy to payments?` | One tool call — `get_recent_deployments` |
| `Show me recent errors on payments` | A different tool — `fetch_error_logs` |
| `What did we deploy to billing?` | The error path — no records for `billing`, so the tool returns `status: "error"` and the agent says so instead of inventing an answer |
| `Payments is failing in prod - check if we deployed recently, look at the error logs, and file a high-severity ticket if it's broken` | All three tools, chained in order — deploys, logs, then the ticket |
| `Who's on call this weekend?` | No tool at all — nothing in the toolset answers this. In `oncall_agent` and `oncall_team` the model just replies; in `oncall_pipeline` both steps answer `SKIPPED` |

In `oncall_agent`, the first three prompts each fire exactly one tool and the fourth fires all three — the instruction gates lookups away from the triage sequence, so a plain "show me the errors" does not file a ticket.

In `oncall_team`, that fourth prompt produces three `transfer_to_agent` hops: lead to `diagnostics_agent`, back to the lead, then out to `ticketing_agent`. In `oncall_pipeline` the same prompt runs both steps in fixed order, and `ticketing_agent` picks the service and commit hash out of session state rather than being told them again.

## How it works

The model never runs your code. It reads the function signature and docstring, decides a tool is needed, and emits a request naming the function and its arguments. ADK is what actually calls the Python function, and feeds the return value back into the conversation as the next turn. The model then keeps going with that result in hand.

Two consequences worth pointing at during the demo:

- **Docstrings are the API.** The docstring and type hints are the only description the model gets, so they are prompt text, not documentation.
- **Descriptions drive routing.** When an LLM agent has sub-agents, it picks one by reading each one's `description` field. Change the wording, change the routing.

## Shared state in `oncall_pipeline`

`oncall_pipeline` is a `SequentialAgent`: it runs `diagnostics_agent` and then `ticketing_agent`, in that order, on every message. The two never talk to each other directly. They share a dict instead — ADK's session state.

A tool writes to state by taking a `tool_context: ToolContext` parameter. ADK injects it and hides it from the model, so it never shows up in the function schema:

```python
def fetch_error_logs(service: str, tool_context: ToolContext) -> dict:
    ...
    tool_context.state["triage_errors"] = lines
```

An agent reads state by templating the key into its instruction, where `?` marks it optional:

```
  service: {triage_service?}
  suspect commit: {triage_commit?}
```

That is how `ticketing_agent` knows the commit hash is `a3f19c2` without it ever appearing in its own conversation. `diagnostics_agent` also sets `output_key="diagnostics_summary"`, which stores its final reply under that key for free.

Two things this buys you beyond passing data around:

- **Ordering enforced in code, not prose.** `create_incident_ticket` returns an error if `triage_errors` is missing. Ask an LLM-routed version of this team to "skip diagnostics and just file the ticket" and it will happily try; the state check is what stops it, and the model then goes and runs diagnostics before filing.
- **One turn instead of two.** `SequentialAgent` guarantees both steps run, with no hand-off latency. The tradeoff is that both steps run on *every* message, which is why each instruction has a `SKIPPED` escape hatch.

Getting control back after a transfer is the thing to be careful about in the LLM-routed `oncall_team`. It works there because `diagnostics_agent` is told, in its instruction, to transfer back to `oncall_lead` when it is done, and carries `disallow_transfer_to_peers=True` so it cannot hand sideways to `ticketing_agent` behind the lead's back. Drop either and triage can stall after the diagnostics step.

## Reference examples

The demo is deliberately small. [`reference/`](reference/) is the other half:
one self-contained file per ADK concept, in this same on-call domain, for when
someone asks a question the demo does not answer.

| | |
| --- | --- |
| Agents & prompts | [basics](reference/01_llm_agent_basics.py), [instructions & templating](reference/02_instructions_and_templating.py) |
| Tools | [function tools](reference/03_function_tools.py), [Google Search](reference/15_google_search.py), [MCP](reference/16_mcp_toolset.py) |
| Memory | [sessions & state](reference/04_sessions_and_state.py), [memory service](reference/05_memory_service.py) |
| Control | [callbacks](reference/06_callbacks.py), [guardrails](reference/07_guardrails.py), [human in the loop](reference/14_human_in_the_loop.py) |
| Composition | [multi-agent](reference/08_multi_agent.py), [workflow agents](reference/09_workflow_agents.py), [custom BaseAgent](reference/10_custom_base_agent.py) |
| Output & runtime | [structured output](reference/11_structured_output.py), [streaming & events](reference/12_streaming_and_events.py), [programmatic Runner](reference/13_programmatic_runner.py) |

See [`reference/README.md`](reference/README.md) for the full index and the
gotchas that cost an afternoon rather than a minute.

`adk web` does not pick these up — they are reading material, run individually
with `python reference/<file>.py`.

## Licence

MIT
