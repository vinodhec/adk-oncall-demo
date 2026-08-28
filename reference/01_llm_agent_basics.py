"""LlmAgent basics - the five fields that define an agent.

WHAT THIS SHOWS
    An `LlmAgent` is a model, a prompt, and a list of tools, given a name.
    `Agent` is an alias for `LlmAgent`; the two are the same class.

    Five fields carry almost all the meaning:

      name          Identifier. Must be a valid Python identifier. Other agents
                    transfer to this agent by this exact string, so it is
                    functional, not cosmetic.
      model          Which model runs the loop, e.g. "gemini-2.5-flash".
      description    One line saying what this agent is for. Ignored when the
                     agent runs alone; read by a *parent* agent to decide
                     whether to route work here. See 08_multi_agent.py.
      instruction    The system prompt. What the agent should do, in what order.
      tools          Python functions the model may ask ADK to call.

WHY IT MATTERS
    Everything else in ADK - workflows, callbacks, memory, guardrails - is a
    layer around this object. If you understand which of these five fields a
    problem belongs to, you usually know where the fix goes:

      "It answers the wrong kind of question"   -> instruction
      "The wrong sub-agent picked up the work"  -> description
      "It called the tool with bad arguments"   -> the tool's docstring (03)
      "It never called the tool at all"         -> instruction, then docstring

RUN IT
    python reference/01_llm_agent_basics.py
"""

from google.adk.agents import Agent  # alias for LlmAgent

from _runner import run

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}


def get_recent_deployments(service: str) -> dict:
    """Returns the most recent deployment for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    deploy = DEPLOYS.get(service.lower())
    if not deploy:
        return {"status": "error", "message": f"No deploy records for {service}."}
    return {"status": "success", "service": service, **deploy}


root_agent = Agent(
    name="oncall_basics",
    model="gemini-2.5-flash",
    description="Answers questions about what was recently deployed.",
    instruction=(
        "You are an on-call assistant. When the user asks what changed or what"
        " shipped for a service, call get_recent_deployments for that service and"
        " report the commit hash and the author exactly as the tool returned them."
        " If the tool returns status 'error', say plainly what is missing."
        " For anything the tool cannot answer, just reply normally."
    ),
    tools=[get_recent_deployments],
)


if __name__ == "__main__":
    run(
        root_agent,
        "What did we deploy to payments?",   # tool call
        "What did we deploy to billing?",    # tool returns an error, agent reports it
        "What time zone are you in?",        # no tool applies, plain reply
    )
