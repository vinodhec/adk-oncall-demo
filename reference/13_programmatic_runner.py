"""The Runner - what `adk web` is doing for you.

WHAT THIS SHOWS
    `adk web` is convenient and completely opaque. This is the same thing,
    written out, which is what you need for tests, batch jobs, a FastAPI
    handler, or anywhere the agent is a library rather than a UI.

    THE RUNNER'S JOB
        The Runner owns the invocation loop. Per turn it:
          1. loads the session,
          2. appends the user message,
          3. calls the agent, which calls the model,
          4. executes any tool the model asked for and feeds the result back,
          5. repeats 3-4 until the model stops asking for tools,
          6. appends every event to the session and applies its state deltas.

        The model never executes anything. It emits a request naming a
        function and its arguments; the Runner is what calls your Python.

    THE SERVICES YOU PLUG IN
        session_service     required. Conversation history and state (04).
        memory_service      optional. Long-term recall (05).
        artifact_service    optional. Files the agent saves or loads.
        credential_service  optional. OAuth tokens for authenticated tools.
        plugins             optional. App-wide callbacks (02).

        `InMemoryRunner` is a Runner with in-memory versions of all of these
        wired up. Use it for tests. Use the explicit `Runner` when any service
        needs to be real.

    THE TWO ENTRY POINTS
        run_async()   async generator of events. The real one.
        run()         blocking wrapper. Convenient in a script, but it runs an
                      event loop internally - do not call it from inside one.

    ONE GOTCHA
        `create_session()` must happen before `run_async()` unless you built
        the Runner with `auto_create_session=True`. A missing session raises
        rather than being created silently.

RUN IT
    python reference/13_programmatic_runner.py
"""

import asyncio

from google.adk.agents import Agent
from google.adk.memory import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "oncall_runner"
USER_ID = "priya"
SESSION_ID = "incident-1"

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}


def get_recent_deployments(service: str) -> dict:
    """Returns the most recent deployment for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    deploy = DEPLOYS.get(service.lower())
    if not deploy:
        return {"status": "error", "message": f"No deploy records for {service}."}
    return {"status": "success", "service": service, **deploy}


root_agent = Agent(
    name="oncall_agent",
    model="gemini-3.6-flash",
    instruction=(
        "You are an on-call assistant. Call get_recent_deployments when asked"
        " what shipped, and report the commit and the author."
    ),
    tools=[get_recent_deployments],
)


async def ask(runner: Runner, prompt: str) -> str:
    """Sends one prompt and returns the agent's final answer as a string.

    This is the function you would call from a web handler or a test.
    """
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    final_text = ""
    async for event in runner.run_async(
        user_id=USER_ID, session_id=SESSION_ID, new_message=message
    ):
        # `is_final_response()` marks the event that ends the turn. Everything
        # before it is a tool call, a tool result, or a partial fragment.
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)

    return final_text.strip()


async def main() -> None:
    # 1. Build the services. Swap any of these for a persistent implementation
    #    and nothing else in this file changes.
    session_service = InMemorySessionService()
    memory_service = InMemoryMemoryService()

    # 2. Build the Runner. `app_name` namespaces sessions and memory; it is
    #    not cosmetic.
    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
        memory_service=memory_service,
    )

    # 3. Create the session before running. Seed state here if the agent's
    #    instruction has {placeholders}.
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
        state={"shift": "night"},
    )

    # 4. Turns. They share the session, so history carries over.
    print(await ask(runner, "What did we deploy to payments?"))
    print(await ask(runner, "Who was that author again?"))

    # 5. Inspect what happened. This is what makes agents testable: the
    #    session is a plain object you can assert against.
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )
    tool_calls = [
        call.name for event in session.events for call in event.get_function_calls()
    ]
    print(f"\nevents: {len(session.events)}   tool calls: {tool_calls}")

    # 6. Archive the finished conversation so a future session can search it.
    await memory_service.add_session_to_memory(session)


if __name__ == "__main__":
    asyncio.run(main())
