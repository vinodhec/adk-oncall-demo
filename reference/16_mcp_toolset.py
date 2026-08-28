"""MCP - using tools you did not write, and publishing the ones you did.

WHAT THIS SHOWS
    The Model Context Protocol is a wire format for exposing tools. An MCP
    server publishes a set of tools; a client connects, asks what is there,
    and calls them. ADK plays both roles:

        AS A CLIENT   McpToolset connects to a server and turns every tool it
                      finds into an ADK tool your agent can call. You write no
                      wrapper functions.

        AS A SERVER   to_mcp_server() exposes your ADK agent as an MCP tool,
                      so Claude Code, an IDE, or any MCP host can drive it.

    INSTALL
        MCP support is not pulled in by `pip install google-adk`:

            pip install mcp

    THE THREE TRANSPORTS
        StdioConnectionParams          Launches the server as a subprocess and
                                       talks over stdin/stdout. Local tools -
                                       a filesystem server, a git server, a
                                       database client on your machine.

        StreamableHTTPConnectionParams Connects to an HTTP endpoint. The
                                       current transport for hosted servers.

        SseConnectionParams            Server-sent events. The older HTTP
                                       transport; prefer StreamableHTTP for
                                       anything new.

    THE THINGS THAT MATTER IN PRACTICE
        tool_filter          An MCP server may publish thirty tools. Every one
                             of them costs tokens in the prompt and adds a
                             wrong turn the model can take. Name the handful
                             you actually want.

        tool_name_prefix     Two servers can publish a tool called "search".
                             A prefix keeps them apart.

        require_confirmation A third-party server's tools run with your
                             agent's authority. `require_confirmation=True`
                             makes ADK pause for a human first (14).

        header_provider      A callback that mints headers per request - the
                             place for a bearer token that expires, rather
                             than a static header baked in at import time.

        Lifecycle            McpToolset owns the connection. Under `adk web`
                             this is handled. Driving a Runner yourself, close
                             the runner (or use it as an async context
                             manager) so the subprocess or session is torn
                             down.

    A NOTE ON TRUST
        Tool descriptions from an MCP server are prompt text your model will
        read and act on. A server you do not control is an input channel into
        your agent's instructions. Filter the tool list, confirm anything with
        real effects, and do not point production agents at servers you have
        not read.

RUN IT
    This file constructs the toolsets but does not connect - the servers below
    are illustrative. Point them at real ones, then:

        python reference/16_mcp_toolset.py
"""

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import (
    McpToolset,
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from mcp import StdioServerParameters

# --------------------------------------------------------------------------
# 1. A local server over stdio
# --------------------------------------------------------------------------
# ADK starts this process itself and speaks MCP over its stdin/stdout. Here:
# the reference filesystem server, scoped to the runbooks directory, so the
# on-call agent can read runbooks without any file-handling code of our own.

runbook_tools = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=[
                "-y",
                "@modelcontextprotocol/server-filesystem",
                # Absolute path. The server refuses anything outside it, which
                # is the sandbox - do not point it at "/".
                "/opt/oncall/runbooks",
            ],
        ),
        timeout=15,
    ),
    # This server publishes a dozen tools including write_file and move_file.
    # We want reads only.
    tool_filter=["read_file", "list_directory", "search_files"],
    tool_name_prefix="runbook",
)


# --------------------------------------------------------------------------
# 2. A hosted server over streamable HTTP
# --------------------------------------------------------------------------
# An incident-tracker server somewhere else. Its tools have real effects, so
# they are gated behind a human (14).

def bearer_headers(ctx) -> dict[str, str]:
    """Mints auth headers per request rather than at import time."""
    # In real code: read a secret manager, refresh an expiring token, or pull
    # a per-user token out of state via ctx.state.
    return {"Authorization": "Bearer <token>"}


incident_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://incidents.internal.example.com/mcp",
        timeout=30,
    ),
    header_provider=bearer_headers,
    tool_filter=["create_incident", "get_incident", "add_incident_note"],
    tool_name_prefix="incidents",
    # Anything that changes the world outside this process waits for a human.
    require_confirmation=True,
)


# --------------------------------------------------------------------------
# Your own tools sit alongside them. MCP tools are just tools.
# --------------------------------------------------------------------------

DEPLOYS = {"payments": {"commit": "a3f19c2", "author": "priya", "at": "09:12 today"}}


def get_recent_deployments(service: str, tool_context: ToolContext) -> dict:
    """Returns the most recent deployment for a service.

    Args:
        service: Service name, e.g. "payments".
    """
    deploy = DEPLOYS.get(service.lower())
    if not deploy:
        return {"status": "error", "message": f"No deploy records for {service}."}
    tool_context.state["suspect_commit"] = deploy["commit"]
    return {"status": "success", "service": service, **deploy}


root_agent = Agent(
    name="mcp_oncall",
    model="gemini-2.5-flash",
    instruction=(
        "You are an on-call assistant.\n"
        "Deploy history comes from get_recent_deployments.\n"
        "Runbooks come from the runbook_* tools - search before you read, and"
        " quote the runbook rather than paraphrasing it.\n"
        "Incidents are filed with the incidents_* tools. These need human"
        " sign-off; if a call comes back needing confirmation, tell the user"
        " exactly what is waiting on them."
    ),
    # A toolset expands to all the tools it exposes, after tool_filter.
    tools=[get_recent_deployments, runbook_tools, incident_tools],
)


# --------------------------------------------------------------------------
# 3. The other direction: this agent AS an MCP server
# --------------------------------------------------------------------------
#
# One MCP tool that runs the agent. An MCP host sends a request string and
# gets the agent's final answer back; one ADK session is kept per connection,
# so successive calls are one conversation.
#
#     from google.adk.tools.mcp_tool import to_mcp_server
#
#     server = to_mcp_server(
#         root_agent,
#         name="oncall_triage",
#         instructions="Triages incidents for our services.",
#     )
#     server.run(transport="stdio")            # a local host
#     # server.run(transport="streamable-http")  # a networked one
#
# Related: `RemoteMcpServer` is a different thing despite the name. It is for
# ManagedAgent, where the Interactions backend opens the MCP session
# server-side and ADK never connects at all.


if __name__ == "__main__":
    # These servers are illustrative - point the params above at real ones
    # before uncommenting.
    #
    # from _runner import run
    # run(root_agent, "Payments is down. Check the deploy, find the runbook,"
    #                 " and open an incident.")
    print(__doc__)
