from google.adk.agents import Agent

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}

DIAGNOSTICS_INSTRUCTION = """You investigate failing services.

Call get_recent_deployments for the service to see what shipped, and fetch_error_logs
for the service to see what is breaking. When the user reports a failure, call both.
Report the commit hash, the author, and the exact error lines you got back.
If a tool returns status "error", say plainly what is missing and stop there.
Do not invent deployments or log lines. You cannot file tickets."""

TICKETING_INSTRUCTION = """You file incident tickets.

Call create_incident_ticket with the affected service, a one-line summary naming the
failing component and the suspect commit hash, and a severity of "low", "medium" or
"high". Report the ticket ID exactly as the tool returned it. Never invent a ticket ID."""

COORDINATOR_INSTRUCTION = """You are the on-call lead. You have no tools of your own.
You route work to your sub-agents.

Diagnose before you file. When a user reports that a service is failing or broken:

Step 1. Delegate to diagnostics_agent to get the recent deployment and the error logs.
Step 2. Only after diagnostics come back, if any log line contains a 5xx error, delegate
        to ticketing_agent to file a high-severity ticket naming the failing component
        and the suspect commit hash.
Step 3. Summarise what was deployed, what the errors were, and the ticket ID.

Never file a ticket before the diagnostics step has returned. Never invent a ticket ID.
For questions your sub-agents cannot answer, reply normally and delegate to no one."""


def get_recent_deployments(service: str) -> dict:
    """Returns the most recent deployment for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    d = DEPLOYS.get(service.lower())
    if not d:
        return {"status": "error", "message": f"No deploy records for {service}."}
    return {"status": "success", "service": service, **d}


def fetch_error_logs(service: str) -> dict:
    """Returns recent error log lines for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    lines = LOGS.get(service.lower())
    if not lines:
        return {"status": "error", "message": f"No logs available for {service}."}
    return {"status": "success", "service": service, "errors": lines}


def create_incident_ticket(service: str, summary: str, severity: str) -> dict:
    """Files an incident ticket and returns its ID.

    Args:
        service: The affected service.
        summary: One-line description of the problem.
        severity: One of "low", "medium" or "high".
    """
    return {"status": "success", "ticket": "INC-402", "service": service,
            "summary": summary, "severity": severity}


diagnostics_agent = Agent(
    name="diagnostics_agent",
    model="gemini-2.5-flash",
    description="Looks up recent deploys and error logs for a service.",
    instruction=DIAGNOSTICS_INSTRUCTION,
    tools=[get_recent_deployments, fetch_error_logs],
)

ticketing_agent = Agent(
    name="ticketing_agent",
    model="gemini-2.5-flash",
    description="Files incident tickets and returns the ticket ID.",
    instruction=TICKETING_INSTRUCTION,
    tools=[create_incident_ticket],
)

root_agent = Agent(
    name="oncall_lead",
    model="gemini-2.5-flash",
    description="Coordinates on-call triage: diagnoses first, then files a ticket.",
    instruction=COORDINATOR_INSTRUCTION,
    sub_agents=[diagnostics_agent, ticketing_agent],
)
