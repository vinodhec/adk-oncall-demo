from google.adk.agents import Agent, SequentialAgent
from google.adk.tools import ToolContext

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}

DIAGNOSTICS_INSTRUCTION = """You investigate failing services. You are step 1 of a
fixed two-step pipeline, so you run on every message.

If the message does not name a service to investigate, call no tools and reply with the
single word SKIPPED.

Otherwise call get_recent_deployments for the service to see what shipped, and
fetch_error_logs for the service to see what is breaking. Call both.
Report the commit hash, the author, and the exact error lines you got back.
If a tool returns status "error", say plainly what is missing and stop there.
Do not invent deployments or log lines. You cannot file tickets."""

TICKETING_INSTRUCTION = """You file incident tickets. You are step 2 of a fixed
two-step pipeline, so you run on every message, including ones with nothing to file.

Diagnostics already ran and left its findings in shared session state:

  service: {triage_service?}
  suspect commit: {triage_commit?}
  error lines: {triage_errors?}

If there are no error lines in state, or none of them contains a 5xx error, call no tools
and reply with the single word SKIPPED.

Otherwise call create_incident_ticket with the affected service, a one-line summary naming
the failing component and the suspect commit hash, and a severity of "low", "medium" or
"high". Take the service and commit from state above; do not ask the user to repeat them.
Report the ticket ID exactly as the tool returned it. Never invent a ticket ID."""

def get_recent_deployments(service: str, tool_context: ToolContext) -> dict:
    """Returns the most recent deployment for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    d = DEPLOYS.get(service.lower())
    if not d:
        return {"status": "error", "message": f"No deploy records for {service}."}
    tool_context.state["triage_service"] = service
    tool_context.state["triage_commit"] = d["commit"]
    return {"status": "success", "service": service, **d}


def fetch_error_logs(service: str, tool_context: ToolContext) -> dict:
    """Returns recent error log lines for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    lines = LOGS.get(service.lower())
    if not lines:
        return {"status": "error", "message": f"No logs available for {service}."}
    tool_context.state["triage_service"] = service
    tool_context.state["triage_errors"] = lines
    return {"status": "success", "service": service, "errors": lines}


def create_incident_ticket(service: str, summary: str, severity: str,
                           tool_context: ToolContext) -> dict:
    """Files an incident ticket and returns its ID.

    Args:
        service: The affected service.
        summary: One-line description of the problem.
        severity: One of "low", "medium" or "high".
    """
    errors = tool_context.state.get("triage_errors")
    if not errors:
        return {"status": "error",
                "message": "No diagnostics in session state. Run diagnostics_agent first."}
    ticket = {"status": "success", "ticket": "INC-402", "service": service,
              "summary": summary, "severity": severity,
              "commit": tool_context.state.get("triage_commit"), "errors": errors}
    tool_context.state["triage_ticket"] = ticket["ticket"]
    return ticket


diagnostics_agent = Agent(
    name="diagnostics_agent",
    model="gemini-3.6-flash",
    description="Looks up recent deploys and error logs for a service.",
    instruction=DIAGNOSTICS_INSTRUCTION,
    tools=[get_recent_deployments, fetch_error_logs],
    output_key="diagnostics_summary",
)

ticketing_agent = Agent(
    name="ticketing_agent",
    model="gemini-3.6-flash",
    description="Files incident tickets and returns the ticket ID.",
    instruction=TICKETING_INSTRUCTION,
    tools=[create_incident_ticket],
)

root_agent = SequentialAgent(
    name="oncall_lead",
    description="Runs on-call triage as a fixed pipeline: diagnose, then file a ticket.",
    sub_agents=[diagnostics_agent, ticketing_agent],
)
