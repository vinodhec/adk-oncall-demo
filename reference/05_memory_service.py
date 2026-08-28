"""Memory service - recall across sessions, as opposed to state within one.

WHAT THIS SHOWS
    State (04) and memory are different things and solve different problems:

        state     A dict. Exact keys, exact values. You decide what goes in.
                  Scoped to a session, a user, or the app.
        memory    A searchable archive of past conversations. You put whole
                  finished sessions in; the agent pulls relevant fragments out
                  by semantic query.

    Use state for "this user's pager channel is slack".
    Use memory for "have we seen this error before, and what fixed it?"

    THE MOVING PARTS
        MemoryService              Where the archive lives.
        add_session_to_memory()    Ingest a finished session. Nothing is
                                   archived automatically - you call this, or
                                   a tool calls tool_context.add_session_to_memory().
        load_memory tool           Give it to an agent and the model decides
                                   when to search, with its own query.
        preload_memory tool        Searches on every single turn using the
                                   user's message and injects the hits before
                                   the model runs. The model never calls it.

        load_memory costs a round trip but only fires when the model thinks it
        needs history. preload_memory always fires. Start with load_memory.

    THE IMPLEMENTATIONS
        InMemoryMemoryService      Keyword matching, no persistence. Fine for
                                   development; it is not a vector search.
        VertexAiMemoryBankService  Managed, with real semantic retrieval and
                                   LLM-extracted memories. Needs a GCP project
                                   and an Agent Engine.
        VertexAiRagMemoryService   Backed by a Vertex AI RAG corpus.

WHY IT MATTERS
    The single most valuable thing an on-call agent can say is "this happened
    on the 14th and rolling back the ledger client fixed it". That answer can
    only come from memory - it is not in state, and it is not in the model.

RUN IT
    python reference/05_memory_service.py
"""

import asyncio

from google.adk.agents import Agent
from google.adk.memory import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext, load_memory
from google.genai import types

APP_NAME = "oncall_memory"
USER_ID = "priya"


# The model calls this itself, from `tools=[load_memory]`. Shown here so you
# can see the shape of what comes back.
async def search_past_incidents(query: str, tool_context: ToolContext) -> dict:
    """Searches previous incidents for anything matching the query.

    Args:
        query: What to look for, e.g. "ledger timeout".
    """
    # Tools may be async. ADK awaits them for you.
    response = await tool_context.search_memory(query)
    hits = []
    for memory in response.memories:
        text = " ".join(part.text for part in (memory.content.parts or []) if part.text)
        hits.append({"author": memory.author, "text": text})
    if not hits:
        return {"status": "error", "message": f"Nothing in memory about {query!r}."}
    return {"status": "success", "hits": hits}


root_agent = Agent(
    name="oncall_with_memory",
    model="gemini-3.6-flash",
    instruction=(
        "You are an on-call assistant with access to past incidents.\n"
        "Before answering any question about whether something has happened"
        " before, call load_memory with a short query built from the user's"
        " question. Quote what you find. If memory returns nothing, say so"
        " plainly - do not guess."
    ),
    # `load_memory` is a ready-made tool. Swap it for `preload_memory` to
    # search automatically on every turn instead.
    tools=[load_memory],
)


async def main() -> None:
    # Both services are passed to the Runner. The agent is unaware of which
    # implementation it is talking to.
    session_service = InMemorySessionService()
    memory_service = InMemoryMemoryService()
    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
        memory_service=memory_service,
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
                        print(f"[{event.author}] {part.text.strip()}")

    # --- Session 1: an incident happens and gets resolved. ---
    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="march-14"
    )
    await turn(
        "march-14",
        "Record this for later: payments threw 500 timeout calling ledger."
        " Commit a3f19c2 was the cause. Rolling it back fixed it in 4 minutes.",
    )

    # --- Archive it. This does not happen on its own. ---
    finished = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="march-14"
    )
    await memory_service.add_session_to_memory(finished)
    print("\n--- session march-14 archived to memory ---")

    # --- Session 2, days later. No shared state, but memory is searchable. ---
    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="march-20"
    )
    await turn("march-20", "Payments is timing out on ledger again. Seen this before?")


if __name__ == "__main__":
    asyncio.run(main())
