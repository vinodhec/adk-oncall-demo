"""Workflow agents - orchestration in code, not in a prompt.

WHAT THIS SHOWS
    Three agents that contain other agents and decide the order they run in.
    None of them calls a model. Their control flow is Python, so it is
    deterministic: the same input takes the same path every time.

        SequentialAgent   Runs sub_agents in list order, once each.
        ParallelAgent     Runs sub_agents concurrently, in isolated branches.
        LoopAgent         Runs sub_agents in order, repeatedly, until
                          max_iterations or until something escalates.

    HOW THEY PASS DATA
        Not by arguments - by session state. An LlmAgent with
        `output_key="findings"` writes its final reply to state["findings"];
        the next agent reads it with a `{findings}` placeholder. That is the
        entire contract between steps.

        For ParallelAgent this matters: branches run concurrently and share
        one state dict, so every branch needs a DIFFERENT output_key or they
        will overwrite each other.

    HOW A LOOP ENDS
        Two ways, and you usually want both:
          - `max_iterations` on the LoopAgent - the hard stop.
          - a tool that sets `tool_context.actions.escalate = True` - the
            "good enough, stop now" signal. ADK ships `exit_loop` for exactly
            this; give it to the agent that judges the result.
        A loop with no escalate path always runs the full max_iterations.

    WHEN TO USE WHICH
        Use a workflow agent when the ORDER is a fact about your process:
        diagnose before you file, always. Use an LlmAgent coordinator (08)
        when the order genuinely depends on what the user said. Prompting a
        coordinator to "always do X then Y" is asking a model to do a job that
        SequentialAgent does for free.

RUN IT
    python reference/09_workflow_agents.py
"""

from google.adk.agents import Agent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.tools import exit_loop

from _runner import run

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}
LOGS = {"payments": ["500 NullPointer in auth_controller", "500 timeout calling ledger"]}
METRICS = {"payments": {"error_rate": "12%", "p99_ms": 4300}}


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


def fetch_metrics(service: str) -> dict:
    """Returns current error rate and latency for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    metrics = METRICS.get(service.lower())
    if not metrics:
        return {"status": "error", "message": f"No metrics for {service}."}
    return {"status": "success", "service": service, **metrics}


# ==========================================================================
# ParallelAgent - three independent lookups at once
# ==========================================================================

deploy_checker = Agent(
    name="deploy_checker",
    model="gemini-3.6-flash",
    instruction="Call get_recent_deployments for the service named by the user."
                " Report the commit and author in one line.",
    tools=[get_recent_deployments],
    output_key="deploy_report",   # distinct key
)

log_checker = Agent(
    name="log_checker",
    model="gemini-3.6-flash",
    instruction="Call fetch_error_logs for the service named by the user."
                " Report the error lines verbatim.",
    tools=[fetch_error_logs],
    output_key="log_report",      # distinct key
)

metric_checker = Agent(
    name="metric_checker",
    model="gemini-3.6-flash",
    instruction="Call fetch_metrics for the service named by the user."
                " Report the error rate and p99 in one line.",
    tools=[fetch_metrics],
    output_key="metric_report",   # distinct key
)

gather_evidence = ParallelAgent(
    name="gather_evidence",
    description="Pulls deploys, logs and metrics at the same time.",
    sub_agents=[deploy_checker, log_checker, metric_checker],
)


# ==========================================================================
# LoopAgent - draft, critique, repeat until good enough
# ==========================================================================

summary_writer = Agent(
    name="summary_writer",
    model="gemini-3.6-flash",
    instruction=(
        "Write a one-paragraph incident summary from this evidence:\n"
        "Deploy: {deploy_report?}\n"
        "Logs: {log_report?}\n"
        "Metrics: {metric_report?}\n"
        "If there is prior feedback, rewrite the summary to address it."
        " Prior feedback: {critique?}\n"
        "Output the summary only."
    ),
    output_key="summary",
)

summary_critic = Agent(
    name="summary_critic",
    model="gemini-3.6-flash",
    instruction=(
        "Review this incident summary: {summary}\n"
        "It is acceptable only if it names the suspect commit, quotes at least"
        " one real error, and gives the error rate.\n"
        "If it is acceptable, call exit_loop and say nothing else.\n"
        "Otherwise reply with the single most important thing that is missing."
    ),
    tools=[exit_loop],   # the escalate path out of the loop
    output_key="critique",
)

refine_summary = LoopAgent(
    name="refine_summary",
    description="Drafts an incident summary and revises it until it passes review.",
    sub_agents=[summary_writer, summary_critic],
    max_iterations=3,   # the hard stop, in case the critic is never satisfied
)


# ==========================================================================
# SequentialAgent - the pipeline. Evidence, then summary, then ticket.
# ==========================================================================

ticket_filer = Agent(
    name="ticket_filer",
    model="gemini-3.6-flash",
    instruction=(
        "Present this final incident summary to the user, verbatim:\n"
        "{summary}\n"
        "Then state which commit should be rolled back first."
    ),
)

root_agent = SequentialAgent(
    name="incident_pipeline",
    description="Gathers evidence, writes a reviewed summary, proposes a rollback.",
    # Runs in exactly this order, every time. No model decides it.
    sub_agents=[gather_evidence, refine_summary, ticket_filer],
)


if __name__ == "__main__":
    run(root_agent, "Payments is broken in prod.")
