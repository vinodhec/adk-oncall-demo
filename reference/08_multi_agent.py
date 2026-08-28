"""Multi-agent - the two ways one agent uses another, and how control returns.

WHAT THIS SHOWS
    There are exactly two ways to connect LLM agents, and they differ in who
    is talking to the user afterwards.

    1. TRANSFER (sub_agents)  -  control moves
           parent = Agent(..., sub_agents=[diagnostics, ticketing])

       The parent's tool list silently gains `transfer_to_agent`. The model
       picks a target by reading each sub-agent's `description` field - not
       its name, not its instruction. The sub-agent then owns the conversation
       and replies directly to the user. The parent is out of the loop until
       control comes back.

       This is why `description` is functional. It is the routing table.

    2. AGENT-AS-TOOL (AgentTool)  -  control stays
           parent = Agent(..., tools=[AgentTool(agent=summariser)])

       The sub-agent runs as a function call, returns its text, and the parent
       carries on with that text in hand. The user never hears from the
       sub-agent. Use this when you want a specialist's answer as an
       ingredient, not as a handoff.

       Rule of thumb: does the user need to be talking to the specialist
       afterwards? Yes -> sub_agents. No -> AgentTool.

    BOUNCE - getting control back after a transfer
       By default a sub-agent may transfer back to its parent, so the model
       can bounce control up when it is done or out of scope. Two fields
       control this:

           disallow_transfer_to_parent=True   dead end - the sub-agent owns
                                              the rest of the conversation
           disallow_transfer_to_peers=True    must go through the parent
                                              rather than sideways to a
                                              sibling

       Setting `disallow_transfer_to_peers=True` on specialists and leaving
       the parent reachable gives you hub-and-spoke routing, which is far
       easier to reason about than a mesh.

    ESCALATION - stopping the enclosing loop
       `tool_context.actions.escalate = True` sets a flag on the event. Inside
       a LoopAgent (09) it ends the loop. Elsewhere it ends the current
       agent's turn and hands control up the tree. It is the "I am done" /
       "I cannot do this, someone else take it" signal.

RUN IT
    python reference/08_multi_agent.py
"""

from google.adk.agents import Agent
from google.adk.tools import AgentTool, ToolContext

from _runner import run

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}


def get_recent_deployments(service: str) -> dict:
    """Returns the most recent deployment for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    deploy = DEPLOYS.get(service.lower())
    if not deploy:
        return {"status": "error", "message": f"No deploy records for {service}."}
    return {"status": "success", "service": service, **deploy}


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
            "severity": severity}


def page_the_lead(reason: str, tool_context: ToolContext) -> dict:
    """Pages the on-call lead when the agent cannot resolve something itself.

    Args:
        reason: Why this needs a human, in one sentence.
    """
    # ESCALATE. Ends this agent's turn and hands control back up the tree.
    # Inside a LoopAgent this is what breaks the loop.
    tool_context.actions.escalate = True
    return {"status": "success", "paged": "oncall-lead", "reason": reason}


# --------------------------------------------------------------------------
# Specialists, reached by TRANSFER
# --------------------------------------------------------------------------

diagnostics_agent = Agent(
    name="diagnostics_agent",
    model="gemini-3.6-flash",
    # This line is what the coordinator's model reads when routing. Rewrite it
    # and you change the routing without touching any other agent.
    description="Looks up recent deploys and error logs for a failing service.",
    instruction=(
        "You investigate failing services. Call get_recent_deployments and"
        " fetch_error_logs for the service, then report the commit, the author"
        " and the exact error lines. You cannot file tickets - once you have"
        " reported the findings, transfer back to the oncall_lead so it can"
        " decide what to do next."
    ),
    tools=[get_recent_deployments, fetch_error_logs],
    # Hub and spoke: this agent may bounce back to the parent, but must not
    # hand straight to ticketing_agent behind the coordinator's back.
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
        " tool returned it - never invent one. If the request is not about"
        " filing a ticket, call page_the_lead."
    ),
    tools=[create_incident_ticket, page_the_lead],
    disallow_transfer_to_peers=True,
)


# --------------------------------------------------------------------------
# A specialist used as a TOOL - the user never sees it
# --------------------------------------------------------------------------

comms_writer = Agent(
    name="comms_writer",
    model="gemini-3.6-flash",
    description="Turns incident findings into a two-sentence status page update.",
    instruction=(
        "Rewrite the incident details you are given as a status page update"
        " for customers. Two sentences. No commit hashes, no stack traces, no"
        " internal service names. Plain, calm language."
    ),
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
        "3. If the user asks for a customer-facing update, call the"
        " comms_writer tool with the incident details and relay what it"
        " returns. Do not transfer for this.\n"
        "Never file a ticket before diagnostics have returned."
    ),
    # Reached by transfer. These agents talk to the user directly.
    sub_agents=[diagnostics_agent, ticketing_agent],
    # Reached as a function call. This agent's output comes back to the lead.
    tools=[AgentTool(agent=comms_writer)],
)


if __name__ == "__main__":
    run(
        root_agent,
        "Payments is failing in prod. Work it end to end.",
        "Now give me something I can put on the status page.",
    )
