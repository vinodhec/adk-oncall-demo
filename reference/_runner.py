"""Shared run helper for the reference examples.

Every example in this folder is about one ADK concept. Wiring up a Runner is
itself one of those concepts, and it is spelled out in full in
`13_programmatic_runner.py`. The other files import `run()` from here so that
the concept they are demonstrating is the only thing in the file.

Nothing in this module is special. It is the same six lines you would write
yourself, wrapped in a function.
"""

from __future__ import annotations

import asyncio

from google.adk.agents import BaseAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

APP_NAME = "adk_reference"
USER_ID = "oncall_engineer"


async def run_async(agent: BaseAgent, *prompts: str, session_id: str = "s1") -> None:
    """Sends each prompt to `agent` in one session and prints what comes back.

    Args:
        agent: The agent to run. Any BaseAgent - LlmAgent, SequentialAgent,
            LoopAgent, or a custom one.
        prompts: User turns, sent in order. They share a session, so state and
            conversation history carry over from one to the next.
        session_id: Session to create and reuse for all the prompts.
    """
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )

    for prompt in prompts:
        print(f"\n\033[1m>>> {prompt}\033[0m")
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session_id, new_message=message
        ):
            # An invocation produces many events: tool calls, tool results,
            # partial text. Here we only print the finished replies.
            if event.content and event.content.parts and not event.partial:
                for part in event.content.parts:
                    if part.text:
                        print(f"[{event.author}] {part.text.strip()}")


def run(agent: BaseAgent, *prompts: str, session_id: str = "s1") -> None:
    """Blocking wrapper around `run_async`, for use under `if __name__`."""
    asyncio.run(run_async(agent, *prompts, session_id=session_id))
