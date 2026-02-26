"""Minimal MCP server lifecycle wrapper used by the daemon."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class MCPHealthSnapshot(TypedDict):
    server_present: bool
    is_serving: bool
    socket_exists: bool
    active_connections: int
    last_accept_age_s: float | None


class TeleClaudeMCPServer:
    """No-op MCP server shim with daemon-compatible lifecycle methods."""

    def __init__(self, *, adapter_client: object, tmux_bridge: object) -> None:
        self._adapter_client = adapter_client
        self._tmux_bridge = tmux_bridge
        self._running = False

    async def start(self) -> None:
        """Start MCP server loop."""
        self._running = True
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop MCP server loop."""
        self._running = False

    async def health_snapshot(self, socket_path: Path) -> MCPHealthSnapshot:
        """Return socket health shape expected by daemon watchdog."""
        return {
            "server_present": True,
            "is_serving": self._running,
            "socket_exists": socket_path.exists(),
            "active_connections": 0,
            "last_accept_age_s": 0.0,
        }
