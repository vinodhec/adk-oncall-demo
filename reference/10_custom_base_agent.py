"""Custom BaseAgent - orchestration logic the workflow agents cannot express.

WHAT THIS SHOWS
    Sequential, Parallel and Loop (09) cover most pipelines. When the shape of
    the work is a real branch - "if the error rate is above 10%, page someone,
    otherwise just file a ticket" - you subclass BaseAgent and write the
    control flow in Python.

    THE CONTRACT
        Override one method:

            async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]

        Inside it you can:
          - read and write state:  ctx.session.state
          - run a sub-agent:       async for event in self.child.run_async(ctx)
          - forward its events:    yield event
          - emit your own event:   yield Event(author=self.name, content=...)

        Whatever you yield reaches the user and the session history. Whatever
        you consume without yielding is invisible - which is how you run a
        sub-agent for its state side-effect only.

    PYDANTIC DETAILS THAT WILL BITE YOU
        BaseAgent is a Pydantic model with `extra="forbid"`. So:
          - declare each sub-agent you hold as a typed class field;
          - pass them through `super().__init__(...)`, not `self.x = ...`;
          - also pass `sub_agents=[...]` so ADK knows the tree shape for
            tracing and transfer.

    WHY IT MATTERS
        This is the escape hatch. Everything above it - SequentialAgent,
        LoopAgent, ParallelAgent - is a BaseAgent subclass written exactly
        this way. Nothing is hidden from you.

RUN IT
    python reference/10_custom_base_agent.py
"""

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from _runner import run

METRICS = {"payments": {"error_rate_pct": 12}, "search": {"error_rate_pct": 2}}


def fetch_metrics(service: str) -> dict:
    """Returns the current error rate for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    metrics = METRICS.get(service.lower())
    if not metrics:
        return {"status": "error", "message": f"No metrics for {service}."}
    return {"status": "success", "service": service, **metrics}


# --------------------------------------------------------------------------
# The sub-agents. Ordinary LlmAgents; the custom agent decides who runs.
# --------------------------------------------------------------------------

triage_agent = LlmAgent(
    name="triage_agent",
    model="gemini-2.5-flash",
    instruction=(
        "Call fetch_metrics for the service the user named. Then reply with"
        " ONLY the integer error rate percentage, e.g. `12`. No other text."
    ),
    tools=[fetch_metrics],
    output_key="error_rate",   # the branch below reads this
)

page_agent = LlmAgent(
    name="page_agent",
    model="gemini-2.5-flash",
    instruction=(
        "This is a severe incident: the error rate is {error_rate}%."
        " Write a two-line page for the on-call lead: what is broken and how"
        " bad it is."
    ),
)

ticket_agent = LlmAgent(
    name="ticket_agent",
    model="gemini-2.5-flash",
    instruction=(
        "This is a minor incident: the error rate is {error_rate}%."
        " Write a one-line ticket description. Do not page anyone."
    ),
)


# --------------------------------------------------------------------------
# The custom agent
# --------------------------------------------------------------------------

class SeverityRouter(BaseAgent):
    """Triages, then branches on the measured error rate.

    Neither SequentialAgent nor LoopAgent can express this: the choice of
    which agent runs second depends on a value produced by the first.
    """

    # Declared as Pydantic fields, because BaseAgent forbids extra attributes.
    triage: LlmAgent
    pager: LlmAgent
    ticketer: LlmAgent
    threshold: int = 10

    def __init__(
        self,
        name: str,
        triage: LlmAgent,
        pager: LlmAgent,
        ticketer: LlmAgent,
        threshold: int = 10,
    ) -> None:
        super().__init__(
            name=name,
            description="Triages a service and pages or files depending on severity.",
            triage=triage,
            pager=pager,
            ticketer=ticketer,
            threshold=threshold,
            # Tell ADK the tree shape. Not optional - tracing and transfer
            # both rely on it.
            sub_agents=[triage, pager, ticketer],
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        # --- Step 1: run the triage agent, forwarding everything it emits.
        async for event in self.triage.run_async(ctx):
            yield event

        # --- Step 2: read what it wrote to state and branch on it, in Python.
        raw = str(ctx.session.state.get("error_rate", "")).strip().rstrip("%")
        try:
            error_rate = int(raw)
        except ValueError:
            # Emit our own event. This reaches the user like any agent reply.
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=f"Could not read an error rate from {raw!r}.")],
                ),
            )
            return

        chosen = self.pager if error_rate >= self.threshold else self.ticketer

        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            f"Error rate {error_rate}% vs threshold"
                            f" {self.threshold}% -> routing to {chosen.name}."
                        )
                    )
                ],
            ),
        )

        # --- Step 3: run only the branch we chose.
        async for event in chosen.run_async(ctx):
            yield event


root_agent = SeverityRouter(
    name="severity_router",
    triage=triage_agent,
    pager=page_agent,
    ticketer=ticket_agent,
    threshold=10,
)


if __name__ == "__main__":
    # payments -> 12% -> pages.  Change to "search" (2%) to take the other branch.
    run(root_agent, "Triage payments.")
