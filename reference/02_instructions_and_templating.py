"""Instructions and templating - putting live values into the system prompt.

WHAT THIS SHOWS
    Four ways to build the text the model sees, in order of increasing power:

    1. A plain string.
           instruction="You are an on-call assistant."

    2. A string with state placeholders. ADK substitutes them from session
       state on every turn, just before the request goes out:
           "{service}"     required - raises KeyError if the key is absent
           "{service?}"    optional - substitutes "" if the key is absent
           "{artifact.runbook.md}"  pulls in an artifact instead of state

       The `?` matters more than it looks. A required placeholder that is not
       yet in state crashes the invocation, so any key that is written mid-
       conversation - rather than seeded at session creation - should be
       optional.

    3. An InstructionProvider: a function taking `ReadonlyContext` and
       returning a string (sync or async). Use it when the prompt needs real
       logic - a branch, a lookup, a formatted list. Call
       `inject_session_state()` inside it if you still want `{}` substitution.

    4. `global_instruction` on the root agent, which applies to every agent in
       the tree. NOTE: deprecated in favour of `GlobalInstructionPlugin`,
       shown at the bottom of this file.

    Also here: `static_instruction`, which is sent verbatim with no
    substitution, ahead of everything else. It exists for prompt caching - put
    the large unchanging block there and the changing part in `instruction`.
    Setting it moves `instruction` out of the system prompt and into the user
    content of the request.

WHY IT MATTERS
    A templated instruction is how an agent gets per-user or per-incident
    context without you rebuilding the agent object. The agent is defined once
    at import time; state changes every turn.

RUN IT
    python reference/02_instructions_and_templating.py
"""

import asyncio

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.runners import InMemoryRunner
from google.adk.utils.instructions_utils import inject_session_state
from google.genai import types

# --------------------------------------------------------------------------
# 2. State placeholders in a plain string
# --------------------------------------------------------------------------

templated_agent = Agent(
    name="templated_oncall",
    model="gemini-3.6-flash",
    instruction=(
        "You are the on-call assistant for the {service} service."
        " The current rotation owner is {oncall_owner}."
        # Optional: this key is only written once an incident is opened, so a
        # required placeholder would blow up on the first turn.
        " Open incident: {active_incident?}"
        " Answer questions about this service only."
    ),
)


# --------------------------------------------------------------------------
# 3. InstructionProvider - a function instead of a string
# --------------------------------------------------------------------------

SEVERITY_POLICY = {
    "payments": "Page immediately. Payments outages are always sev-1.",
    "search": "File a ticket. Search degradation is sev-3 during business hours.",
}


async def build_instruction(ctx: ReadonlyContext) -> str:
    """Builds the prompt from session state, with real branching logic."""
    service = ctx.state.get("service", "unknown")
    policy = SEVERITY_POLICY.get(service, "No policy on file. Escalate to the lead.")

    base = (
        f"You are the on-call assistant for {service}.\n"
        f"Escalation policy for this service: {policy}\n"
        # Placeholders still work if you ask for them explicitly.
        "The rotation owner is {oncall_owner}."
    )
    return await inject_session_state(base, ctx)


provider_agent = Agent(
    name="provider_oncall",
    model="gemini-3.6-flash",
    instruction=build_instruction,
)


# --------------------------------------------------------------------------
# 4a. global_instruction (deprecated, still works)
# --------------------------------------------------------------------------

legacy_global_agent = Agent(
    name="legacy_global",
    model="gemini-3.6-flash",
    # Only the ROOT agent's global_instruction takes effect. Setting it on a
    # sub-agent does nothing.
    global_instruction="Always answer in at most three sentences. Never speculate.",
    instruction="You are the on-call assistant for payments.",
)


# --------------------------------------------------------------------------
# 4b. GlobalInstructionPlugin - the supported replacement
# --------------------------------------------------------------------------
#
# The plugin lives on the App, not on an agent, so it applies to every agent
# the App runs. It accepts the same string-or-InstructionProvider that
# global_instruction did.
#
#     from google.adk.apps import App
#     from google.adk.plugins.global_instruction_plugin import (
#         GlobalInstructionPlugin,
#     )
#
#     app = App(
#         name="oncall",
#         root_agent=root_agent,
#         plugins=[
#             GlobalInstructionPlugin(
#                 "Always answer in at most three sentences. Never speculate."
#             )
#         ],
#     )
#     runner = Runner(app=app, session_service=InMemorySessionService())


# --------------------------------------------------------------------------
# static_instruction - the cacheable block
# --------------------------------------------------------------------------

cached_agent = Agent(
    name="cached_oncall",
    model="gemini-3.6-flash",
    # Sent literally. No {placeholder} substitution happens here.
    static_instruction=(
        "ON-CALL RUNBOOK\n"
        "1. Confirm the alert is real before paging anyone.\n"
        "2. Check the most recent deploy first; most incidents are a bad deploy.\n"
        "3. Roll back before debugging.\n"
        # ... in practice, thousands of tokens that never change.
    ),
    # Substituted per turn, and - because static_instruction is set - carried
    # in the user content rather than the system prompt.
    instruction="You are on call for {service}.",
)


root_agent = templated_agent


async def main() -> None:
    runner = InMemoryRunner(agent=templated_agent, app_name="templating")
    # Placeholder values come from session state, seeded here at creation.
    await runner.session_service.create_session(
        app_name="templating",
        user_id="engineer",
        session_id="s1",
        state={"service": "payments", "oncall_owner": "priya"},
        # Note: no "active_incident" key. The {active_incident?} placeholder
        # resolves to "" rather than raising.
    )

    message = types.Content(
        role="user", parts=[types.Part(text="Which service are you covering, and who owns it?")]
    )
    async for event in runner.run_async(
        user_id="engineer", session_id="s1", new_message=message
    ):
        if event.content and event.content.parts and not event.partial:
            for part in event.content.parts:
                if part.text:
                    print(part.text.strip())


if __name__ == "__main__":
    asyncio.run(main())
