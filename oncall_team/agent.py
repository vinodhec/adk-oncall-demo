from google.adk.agents import Agent

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}


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
    model="gemini-3.6-flash",
    # The coordinator's model reads this line to route. It is the routing table.
    description="Looks up recent deploys and error logs for a failing service.",
    instruction=(
        "You investigate failing services. Call get_recent_deployments and"
        " fetch_error_logs for the service, then report the commit, the author"
        " and the exact error lines. You cannot file tickets - once you have"
        " reported the findings, transfer back to the oncall_lead so it can"
        " decide what to do next."
    ),
    tools=[get_recent_deployments, fetch_error_logs],
    disallow_transfer_to_peers=True,
)

ticketing_agent = Agent(
    name="ticketing_agent",
    model="gemini-3.6-flash",
    description="Files incident tickets and returns the ticket ID.",
    instruction=(
        "You file incident tickets. Call create_incident_ticket with the"
        " service, a one-line summary naming the failing component and the"
        " suspect commit, and a severity. Report the ticket ID exactly as the"
        " tool returned it - never invent one."
    ),
    tools=[create_incident_ticket],
    disallow_transfer_to_peers=True,
)

root_agent = Agent(
    name="oncall_lead",
    model="gemini-3.6-flash",
    description="Coordinates on-call triage: diagnoses first, then files a ticket.",
    instruction=(
        "You are the on-call lead. You route work; you do not diagnose yourself.\n"
        "When a service is reported failing:\n"
        "1. Transfer to diagnostics_agent to get the deploy and the logs.\n"
        "2. When diagnostics come back, if any log line is a 5xx, transfer to"
        " ticketing_agent to file a high-severity ticket.\n"
        "Never file a ticket before diagnostics have returned."
    ),
    sub_agents=[diagnostics_agent, ticketing_agent],
)
