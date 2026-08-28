"""Function tools - the docstring is the API.

WHAT THIS SHOWS
    How a plain Python function becomes something the model can call, and the
    three rules that govern it.

    RULE 1 - The signature and docstring ARE the schema.
        ADK reads the type hints and the docstring and builds the JSON schema
        the model sees. The model never sees the body. So the docstring is
        prompt text, not documentation: it is the only thing telling the model
        when to call this and what to pass.

        Use JSON-friendly types: str, int, float, bool, list, dict, and
        Pydantic models. Avoid default values - ADK marks such a parameter
        optional but the default itself is not communicated to the model, so
        it will guess.

    RULE 2 - Return a dict, and put a status in it.
        The return value is serialised and fed back to the model as the next
        turn. A bare string works but tells the model nothing about success or
        failure. A dict with an explicit "status" key gives the model
        something to branch on, which is what stops it inventing an answer
        when the lookup came up empty.

    RULE 3 - Ask for a `tool_context` parameter when you need the session.
        ADK injects it automatically and strips it from the schema, so the
        model never sees it and cannot pass it. Through it you get:

            tool_context.state              read/write session state (04)
            tool_context.actions            escalate, transfer, skip_summarization
            tool_context.search_memory()    long-term memory (05)
            tool_context.save_artifact()    files
            tool_context.agent_name         who is calling

WHY IT MATTERS
    Most "the agent won't use my tool" and "the agent passes garbage
    arguments" problems are docstring problems, not model problems. Rewriting
    the docstring is usually the fix.

RUN IT
    python reference/03_function_tools.py
"""

from typing import Optional

from google.adk.agents import Agent
from google.adk.tools import ToolContext

from _runner import run

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}


# --------------------------------------------------------------------------
# A minimal tool. Signature + docstring is the whole contract.
# --------------------------------------------------------------------------

def get_recent_deployments(service: str) -> dict:
    """Returns the most recent deployment for a service.

    Call this to find out what shipped before an incident started.

    Args:
        service: Service name, lowercase, e.g. "payments". Not a URL, not a
            team name.

    Returns:
        On success: status, service, commit, author, at.
        On failure: status "error" and a message.
    """
    deploy = DEPLOYS.get(service.lower())
    if not deploy:
        # The error path is as important as the success path. The model reads
        # this and reports it instead of making something up.
        return {"status": "error", "message": f"No deploy records for {service}."}
    return {"status": "success", "service": service, **deploy}


# --------------------------------------------------------------------------
# A tool with an optional parameter, and a list return.
# --------------------------------------------------------------------------

def fetch_error_logs(service: str, contains: Optional[str] = None) -> dict:
    """Returns recent error log lines for a service.

    Args:
        service: Service name, e.g. "payments".
        contains: Optional substring filter. Pass "500" to see only 5xx lines.
            Omit to get everything.
    """
    lines = LOGS.get(service.lower())
    if not lines:
        return {"status": "error", "message": f"No logs available for {service}."}
    if contains:
        lines = [line for line in lines if contains in line]
    return {"status": "success", "service": service, "errors": lines, "count": len(lines)}


# --------------------------------------------------------------------------
# A tool that uses ToolContext. Note `tool_context` is NOT in the docstring
# Args block - the model never sees it and must not try to pass it.
# --------------------------------------------------------------------------

def create_incident_ticket(
    service: str,
    summary: str,
    severity: str,
    tool_context: ToolContext,
) -> dict:
    """Files an incident ticket and returns its ID.

    Args:
        service: The affected service.
        summary: One-line description naming the failing component and the
            suspect commit hash.
        severity: One of "low", "medium" or "high".
    """
    # Read state to make the tool idempotent within a session.
    if existing := tool_context.state.get("incident_ticket"):
        return {"status": "success", "ticket": existing, "note": "already filed"}

    ticket = "INC-402"

    # Write state. The change is recorded on the event this tool call produces,
    # so it persists in the session rather than vanishing with the function.
    tool_context.state["incident_ticket"] = ticket
    tool_context.state["incident_service"] = service

    return {
        "status": "success",
        "ticket": ticket,
        "service": service,
        "summary": summary,
        "severity": severity,
        "filed_by": tool_context.agent_name,
    }


root_agent = Agent(
    name="oncall_tools",
    model="gemini-3.6-flash",
    instruction=(
        "You are an on-call triage assistant.\n"
        "When a service is reported broken: call get_recent_deployments, then"
        " fetch_error_logs, then - if any log line is a 5xx - call"
        " create_incident_ticket with severity 'high'.\n"
        "Report the ticket ID exactly as the tool returned it. Never invent one.\n"
        "If a tool returns status 'error', say what is missing and stop."
    ),
    tools=[get_recent_deployments, fetch_error_logs, create_incident_ticket],
)


if __name__ == "__main__":
    run(
        root_agent,
        "Payments is down in prod, work it.",
        # The second ask hits the idempotency check in state.
        "File that ticket again.",
    )
