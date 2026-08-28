"""Guardrails - rules the model cannot talk its way past.

WHAT THIS SHOWS
    A guardrail is a callback (06) that returns a value instead of None, so
    the model call or the tool call never happens. There are three places to
    put one, and they catch different things:

        INPUT guardrail   before_model_callback
                          Sees the user's message before the model does.
                          Blocks prompt injection, off-topic use, PII.
                          Returning an LlmResponse means the model is never
                          invoked - no token spend, no chance of persuasion.

        TOOL guardrail    before_tool_callback
                          Sees the exact arguments the model chose. This is
                          where you enforce anything with a real-world cost:
                          which service may be touched, what severity may be
                          filed, spending limits, environment allowlists.
                          Returning a dict becomes the tool's result, so the
                          model learns it was refused and why.

        OUTPUT guardrail  after_model_callback
                          Sees the finished reply. Redaction and last-resort
                          filtering.

    THE POINT
        An instruction is advice. The model can be argued out of it, confused
        out of it, or injected out of it. A before_tool_callback that returns
        a refusal is code - there is no prompt that gets past it. Anything
        with consequences belongs in a callback, not only in the prompt.

        Note the difference in what the two return. An input guardrail returns
        a finished LlmResponse, which ends the turn. A tool guardrail returns a
        dict, which the model sees and can react to - it will usually explain
        the refusal to the user, which is what you want.

RUN IT
    python reference/07_guardrails.py
"""

from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from _runner import run

# Only these services may ever be touched by a write tool.
ALLOWED_SERVICES = {"payments", "search", "checkout"}
BLOCKED_TOPICS = ("salary", "performance review", "layoff")


def restart_service(service: str, environment: str) -> dict:
    """Restarts a service. This is a real, destructive action.

    Args:
        service: Service name, e.g. "payments".
        environment: One of "staging" or "prod".
    """
    return {"status": "success", "restarted": service, "environment": environment}


def create_incident_ticket(service: str, summary: str, severity: str) -> dict:
    """Files an incident ticket and returns its ID.

    Args:
        service: The affected service.
        summary: One-line description of the problem.
        severity: One of "low", "medium" or "high".
    """
    return {"status": "success", "ticket": "INC-402", "severity": severity}


# --------------------------------------------------------------------------
# INPUT guardrail - the model is never called
# --------------------------------------------------------------------------

def block_offtopic(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """Refuses HR-adjacent questions before they reach the model."""
    last_user_text = ""
    for content in reversed(llm_request.contents):
        if content.role == "user" and content.parts:
            last_user_text = " ".join(p.text or "" for p in content.parts).lower()
            break

    hit = next((t for t in BLOCKED_TOPICS if t in last_user_text), None)
    if hit is None:
        return None  # proceed to the model

    print(f"  [guardrail] blocked input containing {hit!r}")
    # Returning an LlmResponse ends the turn here. The model is not called.
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    text=(
                        "I only handle service incidents. Please take"
                        f" {hit} questions to your manager or HR."
                    )
                )
            ],
        )
    )


# --------------------------------------------------------------------------
# TOOL guardrail - the function is never called
# --------------------------------------------------------------------------

def enforce_tool_policy(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """Checks the arguments the model actually chose, against real policy."""

    if tool.name == "restart_service":
        service = str(args.get("service", "")).lower()
        environment = str(args.get("environment", "")).lower()

        if service not in ALLOWED_SERVICES:
            print(f"  [guardrail] refused restart of unknown service {service!r}")
            return {
                "status": "error",
                "message": (
                    f"{service!r} is not a service this agent may restart."
                    f" Allowed: {sorted(ALLOWED_SERVICES)}."
                ),
            }

        if environment == "prod" and not tool_context.state.get("prod_approved"):
            print("  [guardrail] refused prod restart - no approval in state")
            # The model sees this dict as the tool result and will relay it.
            return {
                "status": "error",
                "message": (
                    "Production restarts need an approved change record."
                    " Ask the on-call lead to approve, then retry."
                ),
            }

    if tool.name == "create_incident_ticket":
        if args.get("severity") not in {"low", "medium", "high"}:
            # Correcting rather than refusing is also a valid guardrail.
            print("  [guardrail] coerced an invalid severity to 'medium'")
            args["severity"] = "medium"

    return None  # allow the call


# --------------------------------------------------------------------------
# OUTPUT guardrail - the reply is rewritten
# --------------------------------------------------------------------------

def redact_output(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    if not llm_response.content or not llm_response.content.parts:
        return None
    text = "".join(p.text or "" for p in llm_response.content.parts)
    if "@" not in text:
        return None
    print("  [guardrail] redacting an email address from the reply")
    redacted = " ".join(
        "<email redacted>" if "@" in word else word for word in text.split()
    )
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=redacted)])
    )


root_agent = Agent(
    name="guarded_oncall",
    model="gemini-2.5-flash",
    instruction=(
        "You are an on-call assistant. You can restart services and file"
        " incident tickets. Do what the user asks. If a tool refuses, explain"
        " the refusal to the user in plain language and do not retry it."
    ),
    tools=[restart_service, create_incident_ticket],
    before_model_callback=block_offtopic,
    before_tool_callback=enforce_tool_policy,
    after_model_callback=redact_output,
)


if __name__ == "__main__":
    run(
        root_agent,
        "Restart payments in prod.",              # tool guardrail refuses
        "Restart the ledger service in staging.",  # not an allowed service
        "What is priya's salary band?",            # input guardrail, no model call
    )
