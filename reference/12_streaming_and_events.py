"""Streaming and events - the loop under the surface.

WHAT THIS SHOWS
    `runner.run_async()` is an async generator of `Event` objects. A single
    user turn produces many of them. Reading them is how you find out what the
    agent actually did, rather than only what it finally said.

    THE EVENT TYPES YOU WILL SEE, IN ORDER
        1. A model event containing FUNCTION CALLS - the model asking for a
           tool.  event.get_function_calls()
        2. A tool event containing FUNCTION RESPONSES - what your function
           returned.  event.get_function_responses()
        3. Repeat 1-2 for as many rounds as the model needs.
        4. Text events - the reply. In SSE mode these arrive as many partial
           events followed by one complete one.
        5. Transfer events, if a sub-agent took over - visible as
           event.actions.transfer_to_agent.

    THE FIELDS THAT MATTER
        event.author         which agent produced it - the routing audit trail
        event.partial        True for a streaming fragment. Fragments are for
                             display only; do not accumulate them AND also
                             take the final event, or you will double up.
        event.is_final_response()
                             True for the event that ends the turn.
        event.actions        state_delta, transfer_to_agent, escalate - the
                             side effects this event carried
        event.usage_metadata token counts, for cost accounting

    STREAMING MODES
        StreamingMode.NONE   (default) one text event per model turn
        StreamingMode.SSE    token-by-token partial events, for a UI
        StreamingMode.BIDI   bidirectional live audio/video

        `adk web` uses SSE. Setting it from your own code is one RunConfig.

    WHY IT MATTERS
        "The agent gave a wrong answer" is not debuggable. "The model called
        fetch_error_logs with service='Payments-API', got an error back, and
        then answered from its own priors" is - and that is one loop over the
        event stream away.

RUN IT
    python reference/12_streaming_and_events.py
"""

import asyncio

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import InMemoryRunner
from google.genai import types

APP_NAME = "event_stream"
USER_ID = "priya"

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}


def get_recent_deployments(service: str) -> dict:
    """Returns the most recent deployment for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    deploy = DEPLOYS.get(service.lower())
    if not deploy:
        return {"status": "error", "message": f"No deploy records for {service}."}
    return {"status": "success", "service": service, **deploy}


def fetch_error_logs(service: str) -> dict:
    """Returns recent error log lines for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    lines = LOGS.get(service.lower())
    if not lines:
        return {"status": "error", "message": f"No logs available for {service}."}
    return {"status": "success", "service": service, "errors": lines}


root_agent = Agent(
    name="event_oncall",
    model="gemini-3.6-flash",
    instruction=(
        "You are an on-call assistant. When a service is reported broken, call"
        " get_recent_deployments and then fetch_error_logs, then explain what"
        " you found."
    ),
    tools=[get_recent_deployments, fetch_error_logs],
)


async def trace_everything() -> None:
    """Prints every event, unfiltered. This is the debugging view."""
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="trace"
    )

    message = types.Content(
        role="user", parts=[types.Part(text="Payments is broken, what happened?")]
    )

    async for event in runner.run_async(
        user_id=USER_ID, session_id="trace", new_message=message
    ):
        prefix = f"[{event.author}]"

        for call in event.get_function_calls():
            print(f"{prefix} CALL      {call.name}({dict(call.args or {})})")

        for response in event.get_function_responses():
            print(f"{prefix} RESULT    {response.name} -> {response.response}")

        if event.actions and event.actions.transfer_to_agent:
            print(f"{prefix} TRANSFER  -> {event.actions.transfer_to_agent}")

        if event.actions and event.actions.state_delta:
            print(f"{prefix} STATE     {event.actions.state_delta}")

        if event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts)
            if text.strip():
                kind = "PARTIAL" if event.partial else "TEXT   "
                print(f"{prefix} {kind}   {text.strip()[:100]}")

        if event.is_final_response():
            print(f"{prefix} FINAL")


async def stream_tokens() -> None:
    """Prints the reply as it is generated, the way a chat UI would."""
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="sse"
    )

    message = types.Content(
        role="user", parts=[types.Part(text="Summarise the payments incident.")]
    )

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id="sse",
        new_message=message,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        # Print fragments as they arrive; skip the final consolidated event so
        # the text is not printed twice.
        if event.partial and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, end="", flush=True)
    print()


async def main() -> None:
    print("=== every event ===")
    await trace_everything()
    print("\n=== streamed tokens (SSE) ===")
    await stream_tokens()


if __name__ == "__main__":
    asyncio.run(main())
