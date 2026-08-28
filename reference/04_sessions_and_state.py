"""Sessions and state - what the agent remembers, and for how long.

WHAT THIS SHOWS
    THE OBJECTS
        Session          One conversation. Holds the event history and a state
                         dict. Identified by (app_name, user_id, session_id).
        SessionService   Where sessions live. Swap the implementation to change
                         durability; nothing in the agent changes.
        state            A plain dict on the session, readable and writable
                         from tools and callbacks.

    THE FOUR SCOPES - a prefix on the key decides how far the value reaches:

        "commit"          session   this conversation only
        "user:timezone"   user      every session for this user_id
        "app:sev1_policy" app       every user of this app
        "temp:raw_dump"   temp      this invocation only, never persisted

        A prefix is not a namespace convention you can ignore - the service
        reads it and routes the value to different storage.

    THE THREE WAYS TO WRITE IT
        1. Seed it at session creation:      create_session(state={...})
        2. From a tool or callback:          tool_context.state["k"] = v
        3. From an agent's final reply:      LlmAgent(output_key="k")

        Do not mutate `session.state` on a Session object you fetched. That
        write is not attached to an event and will not survive. Write through
        a context, or through `state_delta` on `run_async`.

    THE TWO SERVICES YOU WILL ACTUALLY USE
        InMemorySessionService     Nothing is persisted. Process exits, state
                                   is gone. Right for tests and demos.
        DatabaseSessionService     SQLAlchemy-backed. Survives restarts, and
                                   is what makes "user:" scope meaningful
                                   across days. Needs: pip install google-adk[db]

WHY IT MATTERS
    State is the only channel between one tool call and the next, and between
    one agent and the next in a workflow (09). Choosing the wrong scope is how
    you get an agent that forgets a user's preference every morning, or leaks
    one incident's context into the next.

RUN IT
    python reference/04_sessions_and_state.py
"""

import asyncio

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types

APP_NAME = "oncall_state"
USER_ID = "priya"


def set_pager_preference(channel: str, tool_context: ToolContext) -> dict:
    """Records how this engineer wants to be paged.

    Args:
        channel: One of "sms", "slack" or "phone".
    """
    # "user:" scope - this outlives the conversation and applies to every
    # session this user opens.
    tool_context.state["user:pager_channel"] = channel
    return {"status": "success", "channel": channel}


def note_suspect_commit(commit: str, tool_context: ToolContext) -> dict:
    """Records the commit currently suspected of causing the incident.

    Args:
        commit: Short commit hash, e.g. "a3f19c2".
    """
    # No prefix - session scope. Belongs to this incident conversation only.
    tool_context.state["suspect_commit"] = commit

    # "temp:" scope - available for the rest of this invocation, then dropped.
    # Good for a large intermediate blob you do not want written to the DB.
    tool_context.state["temp:lookup_raw"] = {"commit": commit, "diff_bytes": 4821}

    return {"status": "success", "suspect_commit": commit}


root_agent = Agent(
    name="stateful_oncall",
    model="gemini-3.6-flash",
    instruction=(
        "You are an on-call assistant."
        " The current suspect commit, if one has been recorded, is:"
        " {suspect_commit?}."
        " This engineer's pager channel, if set, is: {user:pager_channel?}."
        " Use set_pager_preference and note_suspect_commit when the user tells"
        " you these things, then confirm what you recorded."
    ),
    tools=[set_pager_preference, note_suspect_commit],
)


# --------------------------------------------------------------------------
# Swapping to a persistent store
# --------------------------------------------------------------------------
#
# The agent above is unchanged. Only the service passed to Runner changes.
#
#     pip install google-adk[db]
#
#     from google.adk.runners import Runner
#     from google.adk.sessions import DatabaseSessionService
#
#     session_service = DatabaseSessionService(db_url="sqlite:///./oncall.db")
#     runner = Runner(
#         agent=root_agent,
#         app_name=APP_NAME,
#         session_service=session_service,
#     )
#
# Now `user:pager_channel` really is remembered tomorrow. Postgres, MySQL and
# anything else SQLAlchemy speaks work the same way via the db_url.


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)

    # 1. Seed state at creation. "app:" scope - shared by every user.
    await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id="incident-1",
        state={"app:sev1_policy": "Page the lead within 5 minutes."},
    )

    async def turn(session_id: str, text: str) -> None:
        print(f"\n>>> [{session_id}] {text}")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session_id, new_message=message
        ):
            if event.content and event.content.parts and not event.partial:
                for part in event.content.parts:
                    if part.text:
                        print(part.text.strip())

    await turn("incident-1", "Page me on slack from now on.")
    await turn("incident-1", "The suspect commit is a3f19c2.")

    # 2. A brand new session for the same user. Session-scoped keys are gone;
    #    "user:" scoped keys are still here.
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="incident-2"
    )
    await turn("incident-2", "What do you know about me and about this incident?")

    # 3. Inspect what actually landed where.
    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="incident-2"
    )
    print("\nstate visible in incident-2:")
    for key, value in sorted(session.state.items()):
        print(f"  {key} = {value!r}")
    # Note: no "suspect_commit" (session scope, belonged to incident-1) and no
    # "temp:lookup_raw" (dropped at the end of its invocation).


if __name__ == "__main__":
    asyncio.run(main())
