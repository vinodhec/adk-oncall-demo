# ADK reference examples

One file per concept, in the same on-call triage domain as the demo, so you
can read any one of them on its own without learning a new scenario first.

These are **not** part of the demo. `adk web` does not pick them up. They
exist so that when someone asks "how do callbacks work?" or "how do I use an
MCP server?" there is a short, correct, runnable file to point at.

Every file follows the same shape:

- a module docstring: what it shows, why it matters, and the gotchas
- the smallest working code that demonstrates it
- a `root_agent`, so you can copy the file into a package and run it under
  `adk web`
- a `__main__` block you can run directly

## Running one

```bash
source .venv/bin/activate
pip install -r requirements.txt
export GOOGLE_API_KEY=...            # or put it in .env at the repo root

cd reference
python 03_function_tools.py
```

Run from inside `reference/` — the files import a shared `run()` helper from
`_runner.py` sitting next to them.

## The files

| File | Concept | The one thing to take away |
| --- | --- | --- |
| [`01_llm_agent_basics.py`](01_llm_agent_basics.py) | `LlmAgent` / `Agent` | Five fields carry the meaning: name, model, description, instruction, tools |
| [`02_instructions_and_templating.py`](02_instructions_and_templating.py) | Instructions, `{var}`, `{var?}`, `global_instruction` | `{var}` raises if the key is absent; `{var?}` does not |
| [`03_function_tools.py`](03_function_tools.py) | Function tools, `ToolContext` | The docstring is prompt text, not documentation |
| [`04_sessions_and_state.py`](04_sessions_and_state.py) | Sessions, state scopes, persistence | The `app:` / `user:` / `temp:` prefix decides where the value is stored |
| [`05_memory_service.py`](05_memory_service.py) | Memory, `load_memory` | Sessions are not archived automatically — you call `add_session_to_memory` |
| [`06_callbacks.py`](06_callbacks.py) | The six agent callbacks | Return `None` to continue; return a value to replace and skip |
| [`07_guardrails.py`](07_guardrails.py) | Input, tool and output guardrails | An instruction is advice; a callback is a rule |
| [`08_multi_agent.py`](08_multi_agent.py) | Transfer, `AgentTool`, bounce, escalate | `sub_agents` hands the user over; `AgentTool` does not |
| [`09_workflow_agents.py`](09_workflow_agents.py) | `Sequential`, `Parallel`, `Loop` | Steps talk to each other through `output_key`, not arguments |
| [`10_custom_base_agent.py`](10_custom_base_agent.py) | Custom `BaseAgent` | The escape hatch for branching the workflow agents cannot express |
| [`11_structured_output.py`](11_structured_output.py) | `output_schema`, `output_key` | The seam between the agent and everything downstream of it |
| [`12_streaming_and_events.py`](12_streaming_and_events.py) | The event stream, SSE | "It gave a wrong answer" is not debuggable; the event trace is |
| [`13_programmatic_runner.py`](13_programmatic_runner.py) | `Runner` | What `adk web` is doing for you, written out |
| [`14_human_in_the_loop.py`](14_human_in_the_loop.py) | Approval gates | The pause lives in code, not in the instruction |
| [`15_google_search.py`](15_google_search.py) | `google_search` grounding | Built-in search cannot share an agent with function tools — isolate it |
| [`16_mcp_toolset.py`](16_mcp_toolset.py) | MCP, as client and as server | `tool_filter` is not optional on a server you did not write |

## Gotchas worth knowing before you start

These are the things that cost an afternoon rather than a minute.

**Callback parameter names are part of the contract.** ADK invokes callbacks
with keyword arguments, so the names must be exactly `callback_context`,
`llm_request`, `llm_response`, `tool`, `args`, `tool_context`,
`tool_response`. Renaming one gives you
`TypeError: got an unexpected keyword argument 'callback_context'`.

**`{var}` in an instruction raises when the key is missing.** Any key written
mid-conversation rather than seeded at session creation should be `{var?}`.

**Parallel branches share one state dict.** Give every branch a distinct
`output_key` or they overwrite each other.

**Built-in search will not share an agent with function tools.** Put
`google_search` on an agent of its own and reach it through `AgentTool`, or
pass `bypass_multi_tools_limit=True`.

**A `before_tool_callback` that mutates `args` does not rewrite the event.**
The trace still shows what the model asked for; your mutation is what reaches
the function. Both being different is the callback working.

**Optional extras are really optional.** `DatabaseSessionService` needs
`pip install google-adk[db]`; `McpToolset` needs `pip install mcp`.

## Verified against

ADK 2.8.0. The APIs here were checked against the installed package, and the
callback wiring, state scoping and workflow ordering were exercised against a
live runtime with a stubbed model.
