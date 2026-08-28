"""Google Search - the built-in grounding tool, and the rule that trips people up.

WHAT THIS SHOWS
    `google_search` is not a function tool. Nothing runs on your machine: ADK
    attaches a `google_search` declaration to the request and the Gemini model
    performs the retrieval server-side, then answers with the results folded
    in. That is why it needs no API key of its own and returns no dict.

        from google.adk.tools import google_search
        Agent(model="gemini-2.5-flash", tools=[google_search])

    THE RULE THAT TRIPS PEOPLE UP
        The Gemini API does not allow a built-in search tool and ordinary
        function calling in the same request. So an agent with
        `tools=[google_search, my_function]`, or with `google_search` AND
        `sub_agents`, is a problem.

        Two ways out:

        a) Isolate it. Put `google_search` on an agent of its own and reach it
           with AgentTool (08). The search agent answers a question; the
           parent carries on with its own tools. This is the portable pattern
           and the one below.

        b) `GoogleSearchTool(bypass_multi_tools_limit=True)`. ADK then wraps
           the search tool in an internal agent-tool for you, which is the
           same trick as (a), applied automatically. Required if the agent
           also has sub_agents.

    CITATIONS
        Grounded answers carry sources on the event, not in the text:
        `event.grounding_metadata.grounding_chunks`. If you are showing search
        results to a user, read them from there - do not ask the model to
        write URLs into its prose, because it will get them wrong.

    RELATED BUILT-INS, SAME RULE
        url_context             fetch and reason about specific URLs
        enterprise_web_search   the enterprise-compliant variant
        VertexAiSearchTool      your own Vertex AI Search datastore
        google_maps_grounding   places and geography

WHY IT MATTERS
    An on-call agent that can read your deploys but not the vendor's status
    page is missing half the picture. Search is how the agent learns about the
    world outside your infrastructure.

RUN IT
    python reference/15_google_search.py
"""

import asyncio

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.tools import AgentTool, google_search
from google.genai import types

APP_NAME = "oncall_search"
USER_ID = "priya"

VENDORS = {"payments": "Stripe", "search": "Elastic Cloud"}


def get_vendor_for_service(service: str) -> dict:
    """Returns the third-party vendor a service depends on.

    Args:
        service: Service name, e.g. "payments".
    """
    vendor = VENDORS.get(service.lower())
    if not vendor:
        return {"status": "error", "message": f"No vendor on file for {service}."}
    return {"status": "success", "service": service, "vendor": vendor}


# --------------------------------------------------------------------------
# The search specialist. google_search is its ONLY tool - that is the point.
# --------------------------------------------------------------------------

search_agent = Agent(
    name="web_search_agent",
    model="gemini-2.5-flash",
    description=(
        "Searches the public web. Use for vendor status pages, CVEs, error"
        " messages from third-party libraries - anything not in our own"
        " systems."
    ),
    instruction=(
        "Search the web for what you are asked and answer in two or three"
        " sentences. Say when the information is from and name the source."
        " If the search turns up nothing useful, say so rather than guessing."
    ),
    tools=[google_search],
)


# --------------------------------------------------------------------------
# The coordinator. Its own function tools, plus search reached as a tool.
# --------------------------------------------------------------------------

root_agent = Agent(
    name="oncall_with_search",
    model="gemini-2.5-flash",
    instruction=(
        "You are an on-call assistant.\n"
        "For anything about our own services, call get_vendor_for_service.\n"
        "For anything about the outside world - a vendor's outage, a CVE, an"
        " unfamiliar error string - call web_search_agent with a specific"
        " query and relay what it says.\n"
        "Do not answer questions about current vendor status from memory."
    ),
    # A function tool and a search agent-tool coexist happily. `google_search`
    # itself in this list alongside get_vendor_for_service would not.
    tools=[get_vendor_for_service, AgentTool(agent=search_agent)],
)


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="s1"
    )

    prompt = (
        "Payments is throwing errors. Which vendor does it depend on, and is"
        " that vendor reporting an incident right now?"
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    async for event in runner.run_async(
        user_id=USER_ID, session_id="s1", new_message=message
    ):
        if event.content and event.content.parts and not event.partial:
            text = "".join(p.text or "" for p in event.content.parts)
            if text.strip():
                print(f"[{event.author}] {text.strip()}")

        # Sources for a grounded answer live here, not in the text.
        if event.grounding_metadata and event.grounding_metadata.grounding_chunks:
            for chunk in event.grounding_metadata.grounding_chunks:
                if chunk.web:
                    print(f"    source: {chunk.web.title} - {chunk.web.uri}")


if __name__ == "__main__":
    asyncio.run(main())
