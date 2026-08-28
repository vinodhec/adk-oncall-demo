"""Callbacks - hooks around the model call and the tool call.

WHAT THIS SHOWS
    Six hooks on LlmAgent. The rule that governs all of them:

        Return None  -> carry on as normal.
        Return a value -> that value REPLACES what would have happened, and
                          the underlying model call or tool call is SKIPPED.

    THE HOOKS AND THEIR SIGNATURES

        before_agent_callback(callback_context) -> Optional[Content]
        after_agent_callback(callback_context)  -> Optional[Content]
            Around the whole agent. Returning Content skips the agent entirely.

        before_model_callback(callback_context, llm_request) -> Optional[LlmResponse]
            Fires before every request to the model. You can read and MUTATE
            `llm_request` in place - add a system instruction, trim history.
            Returning an LlmResponse short-circuits the model. This is where
            input guardrails live (07).

        after_model_callback(callback_context, llm_response) -> Optional[LlmResponse]
            Fires on the way back. Returning a new LlmResponse rewrites what
            the model said. Output filtering and redaction live here.

        before_tool_callback(tool, args, tool_context) -> Optional[dict]
            Fires before each tool call, with the arguments the model chose.
            Mutate `args` in place to correct them. Returning a dict becomes
            the tool result and the function is never called - that is both a
            tool guardrail (07) and the basis of human-in-the-loop (14).

        after_tool_callback(tool, args, tool_context, tool_response) -> Optional[dict]
            Fires after. Returning a dict replaces the tool's result.

    Every hook may be async, and every hook accepts a LIST of callbacks. With a
    list, ADK runs them in order and stops at the first one that returns
    non-None.

    THE GOTCHA: PARAMETER NAMES ARE PART OF THE CONTRACT
        ADK invokes these with KEYWORD arguments, not positional ones. Rename
        `callback_context` to `ctx` and you get:

            TypeError: before_model() got an unexpected keyword argument
            'callback_context'

        The names ADK passes, exactly:

            callback_context, llm_request
            callback_context, llm_response
            tool, args, tool_context
            tool, args, tool_context, tool_response

WHY IT MATTERS
    Callbacks are where the things you cannot put in a prompt go: audit
    logging, redaction, caching, rate limits, injecting a value the model must
    not be trusted to supply. A prompt is a request; a callback is a rule.

RUN IT
    python reference/06_callbacks.py
"""

from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from _runner import run

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


# --------------------------------------------------------------------------
# before_model - inspect and mutate the outbound request
# --------------------------------------------------------------------------

def before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    print(
        f"  [before_model] agent={callback_context.agent_name}"
        f" contents={len(llm_request.contents)}"
    )

    # Mutating the request in place is a normal thing to do here. This appends
    # to the system instruction for this one call, without touching the agent.
    shift = callback_context.state.get("shift", "day")
    llm_request.append_instructions([f"The current on-call shift is: {shift}."])

    # Returning None means "go ahead and call the model".
    return None


# --------------------------------------------------------------------------
# after_model - rewrite what came back
# --------------------------------------------------------------------------

def after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    if not llm_response.content or not llm_response.content.parts:
        return None

    text = "".join(p.text or "" for p in llm_response.content.parts)
    if "a3f19c2" not in text:
        return None

    # Redact the commit hash. Returning a new LlmResponse replaces the original.
    print("  [after_model] redacting a commit hash")
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text=text.replace("a3f19c2", "<redacted>"))],
        )
    )


# --------------------------------------------------------------------------
# before_tool - correct the model's arguments
# --------------------------------------------------------------------------

def before_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    print(f"  [before_tool] {tool.name}({args})")

    # Models pass "Payments" or "payments-api" often enough that normalising
    # here is cheaper than another sentence of prompt. Mutate args in place.
    #
    # Worth knowing: the event in the session still records what the MODEL
    # asked for. Your mutation is what reaches the function. So the trace
    # shows service="Payments-API" and the tool result shows "payments" -
    # that is the callback working, not a bug.
    if "service" in args and isinstance(args["service"], str):
        args["service"] = args["service"].strip().lower().removesuffix("-api")

    # Returning None runs the real function. Returning a dict would skip it.
    return None


# --------------------------------------------------------------------------
# after_tool - annotate or replace the result
# --------------------------------------------------------------------------

def after_tool(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict,
) -> Optional[dict]:
    print(f"  [after_tool] {tool.name} -> {tool_response.get('status')}")

    if tool_response.get("status") == "error":
        # Give the model a next step rather than a dead end.
        return {**tool_response, "hint": "Ask the user to confirm the service name."}
    return None


root_agent = Agent(
    name="observed_oncall",
    model="gemini-2.5-flash",
    instruction=(
        "You are an on-call assistant. Call get_recent_deployments when asked"
        " what shipped, and report the commit and author."
    ),
    tools=[get_recent_deployments],
    before_model_callback=before_model,
    after_model_callback=after_model,
    # A list also works: before_tool_callback=[normalise, audit, rate_limit]
    before_tool_callback=before_tool,
    after_tool_callback=after_tool,
)


if __name__ == "__main__":
    run(
        root_agent,
        "What shipped to Payments-API?",   # before_tool normalises the argument
        "What shipped to checkout?",       # after_tool adds a hint to the error
    )
