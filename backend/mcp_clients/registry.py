"""MCP client wiring.

Connects the backend/agents to our MCP servers:
  - cronometer     : Streamable HTTP (our FastMCP server, default :8001)
  - google_health  : stdio (the pinned npx package)

Each helper opens a short-lived session. For the agent loop we'll hold sessions
open; for health checks and one-off tool calls, connect-per-call is simplest.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


# The Google Health MCP exposes ~26 tools, most of them setup/meta (onboarding,
# demo, auth, privacy, profile). Exposing all of them to the model buries the few
# useful data-reading tools and confuses smaller models. Allow only these.
GOOGLE_HEALTH_TOOLS = (
    "google_health_connection_status",
    "google_health_data_inventory",
    "google_health_list_data_types",
    "google_health_list_data_points",
    "google_health_daily_summary",
    "google_health_weekly_summary",
    "google_health_daily_rollup",
    "google_health_rollup",
)


@dataclass(frozen=True)
class ServerRef:
    name: str
    kind: str  # "http" | "stdio"
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    # If set, only these tool names are exposed to the model (others are hidden).
    tool_allowlist: tuple[str, ...] | None = None


def server_refs(settings: Settings | None = None) -> list[ServerRef]:
    s = settings or get_settings()
    return [
        ServerRef("cronometer", "http", url=s.cronometer_mcp_url),
        ServerRef(
            "google_health",
            "stdio",
            command=s.google_health_mcp_cmd,
            args=tuple(s.google_health_args_list),
            tool_allowlist=GOOGLE_HEALTH_TOOLS,
        ),
    ]


@contextlib.asynccontextmanager
async def open_session(ref: ServerRef) -> AsyncIterator[ClientSession]:
    """Open an initialized MCP ClientSession for a server reference."""
    if ref.kind == "http":
        async with streamablehttp_client(ref.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    elif ref.kind == "stdio":
        params = StdioServerParameters(command=ref.command, args=list(ref.args))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:  # pragma: no cover - guarded by construction
        raise ValueError(f"Unknown server kind: {ref.kind}")


async def list_tools(ref: ServerRef) -> list[str]:
    """Return the tool names exposed by a server (raises on connection failure)."""
    async with open_session(ref) as session:
        result = await session.list_tools()
        return [t.name for t in result.tools]


async def call_tool(ref: ServerRef, tool: str, arguments: dict[str, Any]) -> Any:
    """Call a single tool and return its structured/text content."""
    async with open_session(ref) as session:
        result = await session.call_tool(tool, arguments)
        return result.structuredContent or [
            c.text for c in result.content if getattr(c, "type", None) == "text"
        ]


async def health_check() -> dict[str, bool]:
    """Best-effort reachability of each MCP server (never raises)."""
    status: dict[str, bool] = {}
    for ref in server_refs():
        try:
            tools = await list_tools(ref)
            status[ref.name] = len(tools) > 0
        except Exception as exc:  # noqa: BLE001 - health check reports, never fails
            logger.warning("MCP %s unreachable: %s", ref.name, exc)
            status[ref.name] = False
    return status
