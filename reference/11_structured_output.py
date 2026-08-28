"""Structured output - getting a typed object back instead of prose.

WHAT THIS SHOWS
    `output_schema` constrains the agent's final reply to a Pydantic model.
    The model is forced to emit conforming JSON, ADK validates it, and the
    result lands in state under `output_key` as a dict.

        Agent(
            output_schema=IncidentReport,
            output_key="report",
        )

    Then `session.state["report"]` is a dict matching the schema, and
    `IncidentReport(**session.state["report"])` gives you the object.

    WHERE THE DESCRIPTIONS GO
        Field descriptions in the Pydantic model are sent to the model as part
        of the schema. They are prompt text, exactly like a tool docstring
        (03). `Field(description="Short commit hash, e.g. a3f19c2")` does more
        work than another paragraph of instruction.

    THE `output_schema` + `tools` QUESTION
        Older ADK forbade combining them. Current ADK allows it: tools are
        available during the reasoning loop, and the structure is enforced
        only on the final answer. Still, the cleanest pattern is to keep them
        apart - one agent gathers with tools, a second agent with
        `output_schema` and `include_contents="default"` shapes the result.
        That second agent is easy to test and cheap to re-run.

    WHY IT MATTERS
        This is the seam between the agent and the rest of your system. Prose
        has to be parsed; a validated dict can be written to a database, sent
        to PagerDuty, or asserted against in a test. Anything downstream of
        the agent should be reading `output_schema` output, not regexing a
        paragraph.

RUN IT
    python reference/11_structured_output.py
"""

import asyncio
from typing import Literal

from google.adk.agents import Agent, SequentialAgent
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field

APP_NAME = "structured_oncall"
USER_ID = "priya"

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


# --------------------------------------------------------------------------
# The schema. Every description here is seen by the model.
# --------------------------------------------------------------------------

class IncidentReport(BaseModel):
    """A triaged incident, ready to be written to the incident tracker."""

    service: str = Field(description="The affected service, lowercase.")
    severity: Literal["low", "medium", "high"] = Field(
        description="high if any 5xx errors are present, otherwise medium."
    )
    suspect_commit: str = Field(
        description="Short commit hash of the most recent deploy, e.g. a3f19c2."
        " Use 'unknown' if no deploy was found."
    )
    failing_component: str = Field(
        description="The component named in the errors, e.g. auth_controller."
    )
    evidence: list[str] = Field(
        description="The error log lines, quoted verbatim. Do not paraphrase."
    )
    recommended_action: str = Field(
        description="One sentence. What the on-call engineer should do first."
    )


# --------------------------------------------------------------------------
# Step 1: gather, with tools. Free-form output.
# --------------------------------------------------------------------------

investigator = Agent(
    name="investigator",
    model="gemini-2.5-flash",
    instruction=(
        "Call get_recent_deployments and then fetch_error_logs for the service"
        " the user named. Report everything both tools returned, verbatim."
        " Do not summarise or interpret."
    ),
    tools=[get_recent_deployments, fetch_error_logs],
    output_key="raw_findings",
)


# --------------------------------------------------------------------------
# Step 2: shape it. No tools, structure enforced.
# --------------------------------------------------------------------------

reporter = Agent(
    name="reporter",
    model="gemini-2.5-flash",
    instruction=(
        "Turn these findings into an incident report.\n\n{raw_findings}\n\n"
        "Use only what is in the findings. Do not invent a commit hash."
    ),
    output_schema=IncidentReport,
    output_key="report",
)


root_agent = SequentialAgent(
    name="structured_triage",
    description="Investigates an incident and emits a validated IncidentReport.",
    sub_agents=[investigator, reporter],
)


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="s1"
    )

    message = types.Content(
        role="user", parts=[types.Part(text="Payments is broken in prod.")]
    )
    async for _ in runner.run_async(
        user_id=USER_ID, session_id="s1", new_message=message
    ):
        pass

    session = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id="s1"
    )

    # state["report"] is a plain dict, already validated against the schema.
    report = IncidentReport(**session.state["report"])

    print(f"service:      {report.service}")
    print(f"severity:     {report.severity}")
    print(f"commit:       {report.suspect_commit}")
    print(f"component:    {report.failing_component}")
    print(f"action:       {report.recommended_action}")
    for line in report.evidence:
        print(f"  evidence:   {line}")

    # This is the point of the exercise - a branch on a typed field, not on
    # whether the word "critical" appeared somewhere in a paragraph.
    if report.severity == "high":
        print("\n-> would page the on-call lead")


if __name__ == "__main__":
    asyncio.run(main())
