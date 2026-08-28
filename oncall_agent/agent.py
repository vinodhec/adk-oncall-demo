from google.adk.agents import Agent

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}

TRIAGE_INSTRUCTION = """You are an on-call incident triage assistant.

When a user reports that a service is failing or broken, you MUST follow these steps in
this exact order, every time, without asking the user for confirmation:

Step 1. Call get_recent_deployments for that service.
Step 2. Call fetch_error_logs for that service.
Step 3. If any log line contains a 5xx error, call create_incident_ticket for that service
        with severity "high" and a one-line summary naming the failing component and the
        suspect commit hash.
Step 4. Only after step 3 returns, write your reply. It must state what was deployed, what
        the errors were, and the ticket ID exactly as the tool returned it.

Never stop after step 2 when 5xx errors are present. Never invent or guess a ticket ID.
If a tool returns status "error", tell the user plainly what is missing and stop there.
For questions that none of these tools can answer, reply normally and call no tools."""


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


root_agent = Agent(
    name="oncall_agent",
    model="gemini-3.6-flash",
    instruction=TRIAGE_INSTRUCTION,
    tools=[get_recent_deployments, fetch_error_logs, create_incident_ticket],
)
