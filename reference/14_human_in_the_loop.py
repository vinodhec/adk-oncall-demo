"""Human in the loop - making the agent stop and ask before it acts.

WHAT THIS SHOWS
    Three mechanisms, from least to most built-in. Pick by how much
    infrastructure you already have.

    1. before_tool_callback gate  (works everywhere, no extra machinery)
       The callback checks whether approval is on record. If not, it returns a
       dict instead of None - so the real function never runs, and the model
       receives "pending approval" as the tool result and relays that to the
       user. A separate approve tool records the approval in state; the model
       retries and the callback lets it through.

       Everything you need is in this file, and it works with any front end,
       because "approval" is just a key in session state.

    2. FunctionTool(require_confirmation=True)  (ADK's own protocol)
           tools=[FunctionTool(restart_service, require_confirmation=True)]

       ADK pauses the call and emits a confirmation request on the event
       (`event.actions.requested_tool_confirmations`). Your UI shows it, the
       user accepts, and you resume the invocation with the confirmation
       attached. `adk web` renders this for you. Doing it from your own code
       means handling the resume, which is why the callback gate above is
       often the shorter path.

       `tool_context.request_confirmation(hint=...)` does the same thing from
       inside a tool, when whether to ask depends on the arguments.

    3. LongRunningFunctionTool  (for approvals that take minutes or days)
       The tool returns immediately with a ticket ID, the invocation ends, and
       the answer is delivered later when the human responds. ADK ships
       `get_user_choice` as a ready-made example of one.

    THE RULE
        The pause must live in code, not in the instruction. "Ask the user
        before restarting anything" is advice a model can skip; a
        before_tool_callback that returns early cannot be skipped. Same
        principle as guardrails (07) - this is that mechanism, with a resume.

RUN IT
    python reference/14_human_in_the_loop.py
"""

from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.tools import BaseTool, FunctionTool, ToolContext

from _runner import run

# Tools whose effects are visible to customers need a human first.
NEEDS_APPROVAL = {"restart_service", "roll_back_deploy"}


def restart_service(service: str, environment: str) -> dict:
    """Restarts a service. Causes a brief outage.

    Args:
        service: Service name, e.g. "payments".
        environment: One of "staging" or "prod".
    """
    return {"status": "success", "restarted": service, "environment": environment}


def roll_back_deploy(service: str, commit: str) -> dict:
    """Rolls a service back to the deploy before the given commit.

    Args:
        service: Service name, e.g. "payments".
        commit: The bad commit to roll back past, e.g. "a3f19c2".
    """
    return {"status": "success", "service": service, "rolled_back_past": commit}


def approve_pending_action(tool_context: ToolContext) -> dict:
    """Records the on-call engineer's approval for the pending action.

    Call this only when the user has explicitly said yes, go ahead, approved,
    or similar. Never call it on your own initiative.
    """
    pending = tool_context.state.get("pending_action")
    if not pending:
        return {"status": "error", "message": "There is no action awaiting approval."}

    tool_context.state["approved_action"] = pending
    tool_context.state["pending_action"] = None
    return {"status": "success", "approved": pending}


# --------------------------------------------------------------------------
# 1. The gate
# --------------------------------------------------------------------------

def require_human_approval(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    if tool.name not in NEEDS_APPROVAL:
        return None  # harmless tool, let it run

    # Identify this specific call, not just the tool, so approving a staging
    # restart does not silently approve a prod one.
    action = f"{tool.name}({', '.join(f'{k}={v}' for k, v in sorted(args.items()))})"

    if tool_context.state.get("approved_action") == action:
        # Approved. Consume the approval so it is good for one use only.
        tool_context.state["approved_action"] = None
        print(f"  [hitl] approved, running {action}")
        return None

    # Not approved. Record what is waiting, and return a result WITHOUT ever
    # calling the function.
    print(f"  [hitl] holding {action} for approval")
    tool_context.state["pending_action"] = action
    return {
        "status": "pending_approval",
        "action": action,
        "message": (
            f"This needs sign-off before it runs: {action}."
            " Ask the on-call engineer to confirm, and if they agree call"
            " approve_pending_action and then retry."
        ),
    }


root_agent = Agent(
    name="hitl_oncall",
    model="gemini-2.5-flash",
    instruction=(
        "You are an on-call assistant that can restart services and roll back"
        " deploys.\n"
        "If a tool comes back with status 'pending_approval', tell the user"
        " exactly what needs approving and ask them to confirm. Do not retry"
        " it yet.\n"
        "When the user confirms, call approve_pending_action, then retry the"
        " original tool with the same arguments.\n"
        "If the user declines, drop it and say so."
    ),
    tools=[restart_service, roll_back_deploy, approve_pending_action],
    before_tool_callback=require_human_approval,
)


# --------------------------------------------------------------------------
# 2. The same pause, using ADK's own confirmation protocol
# --------------------------------------------------------------------------
# No callback and no approve tool. ADK holds the call and emits a confirmation
# request; `adk web` renders it as a prompt. Driving this from your own code
# means reading `event.actions.requested_tool_confirmations`, collecting the
# answer, and resuming the invocation with the confirmation attached - which
# is why the callback gate above is often less work outside `adk web`.

confirming_agent = Agent(
    name="hitl_builtin",
    model="gemini-2.5-flash",
    instruction=(
        "You are an on-call assistant that can restart services."
        " Restart what the user asks for."
    ),
    tools=[
        FunctionTool(restart_service, require_confirmation=True),
        # `require_confirmation` also takes a callable, so you can ask only
        # when it matters:
        #   FunctionTool(
        #       roll_back_deploy,
        #       require_confirmation=lambda **kwargs: kwargs.get("service") == "payments",
        #   )
    ],
)


if __name__ == "__main__":
    run(
        root_agent,
        "Roll payments back past a3f19c2.",   # held for approval
        "Yes, go ahead.",                      # approved, then retried
        "Now restart payments in prod.",       # a new action - held again
    )
