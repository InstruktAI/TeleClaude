"""REST API server for TeleClaude using FastAPI.

Provides HTTP endpoints for programmatic control of terminal sessions.
Part of modular architecture - will become REST adapter.
"""

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from teleclaude.core.session_manager import SessionManager
    from teleclaude.core.terminal_bridge import TerminalBridge

logger = logging.getLogger(__name__)


class TeleClaudeAPI:
    """FastAPI application for TeleClaude REST API."""

    def __init__(
        self,
        session_manager: "SessionManager",
        terminal_bridge: "TerminalBridge",
        bind_address: str = "127.0.0.1",
        port: int = 6666,
    ):
        """Initialize FastAPI application.

        Args:
            session_manager: Session manager instance
            terminal_bridge: Terminal bridge instance
            bind_address: Address to bind to (default: 127.0.0.1 for security)
            port: Port to listen on (default: 6666)
        """
        self.session_manager = session_manager
        self.terminal_bridge = terminal_bridge
        self.bind_address = bind_address
        self.port = port
        self.start_time = time.time()

        # Create FastAPI app
        self.app = FastAPI(
            title="TeleClaude REST API",
            description="Programmatic control of terminal sessions",
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )

        # Register routes
        self._register_routes()

    def _register_routes(self) -> None:
        """Register API routes."""

        @self.app.get("/health")
        async def health() -> dict[str, Any]:
            """Health check endpoint.

            Returns:
                Health status information
            """
            return self._success_response(
                {
                    "status": "healthy",
                    "uptime_seconds": int(time.time() - self.start_time),
                    "sessions": {
                        "active": await self.session_manager.count_sessions(status="active"),
                        "total": await self.session_manager.count_sessions(),
                    },
                }
            )

        @self.app.get("/api/v1/sessions/{session_id}/output")
        async def get_session_output(
            session_id: str,
            lines: Optional[int] = Query(None, description="Number of lines to return (default: all)"),
            from_line: int = Query(0, description="Start from line N (default: 0)"),
        ) -> dict[str, Any]:
            """Get terminal output for a session.

            Args:
                session_id: Session UUID
                lines: Number of lines to return (optional)
                from_line: Start line number (default: 0)

            Returns:
                Session output with line metadata
            """
            # Get session from database
            session = await self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(
                    status_code=404,
                    detail=self._error_response("SESSION_NOT_FOUND", f"Session {session_id} does not exist"),
                )

            # Get output from tmux
            try:
                output = await self.terminal_bridge.capture_pane(session.tmux_session_name)
            except Exception as e:
                logger.error("Error capturing output for session %s: %s", session_id, e)
                raise HTTPException(
                    status_code=500, detail=self._error_response("INTERNAL_ERROR", f"Failed to capture output: {e}")
                )

            # Split into lines and apply filters
            output_lines = output.split("\n")
            total_lines = len(output_lines)

            # Apply from_line offset
            if from_line > 0:
                output_lines = output_lines[from_line:]

            # Apply lines limit
            if lines is not None and lines > 0:
                output_lines = output_lines[:lines]
                to_line = from_line + lines
            else:
                to_line = total_lines

            return self._success_response(
                {
                    "output": "\n".join(output_lines),
                    "total_lines": total_lines,
                    "from_line": from_line,
                    "to_line": min(to_line, total_lines),
                }
            )

    def _success_response(self, data: Any) -> dict[str, Any]:
        """Create standard success response.

        Args:
            data: Response data

        Returns:
            Standardized success response
        """
        return {
            "success": True,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _error_response(self, code: str, message: str) -> dict[str, Any]:
        """Create standard error response.

        Args:
            code: Error code
            message: Error message

        Returns:
            Standardized error response
        """
        return {
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_asgi_app(self) -> FastAPI:
        """Get ASGI application for uvicorn.

        Returns:
            FastAPI application instance
        """
        return self.app
