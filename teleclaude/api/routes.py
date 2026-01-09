"""API route definitions - thin wrappers around existing MCP handlers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.api.models import (
    AgentAvailability,
    ComputerResponse,
    CreateSessionRequest,
    ProjectResponse,
    SendMessageRequest,
    SessionResponse,
    TodoResponse,
)
from teleclaude.core.db import db
from teleclaude.core.models import ThinkingMode

if TYPE_CHECKING:
    from teleclaude.mcp_server import TeleClaudeMCPServer

logger = get_logger(__name__)

router = APIRouter()

# Will be set by daemon when starting API server
_mcp_server: TeleClaudeMCPServer | None = None


def set_mcp_server(server: TeleClaudeMCPServer) -> None:
    """Set the MCP server instance for route handlers to use."""
    global _mcp_server  # noqa: PLW0603 - Intentional global state for API server
    _mcp_server = server


def get_mcp() -> TeleClaudeMCPServer:
    """Get MCP server instance."""
    if _mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    return _mcp_server


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(computer: str | None = None) -> list[SessionResponse]:
    """List sessions from all computers or specific computer via Redis."""
    mcp = get_mcp()
    sessions = await mcp.teleclaude__list_sessions(computer=computer or "local")

    # Convert to SessionResponse format
    result: list[SessionResponse] = []
    for session in sessions:
        result.append(
            SessionResponse(
                session_id=session["session_id"],
                computer=session["computer"],
                title=session.get("title"),
                tmux_session_name=session.get("tmux_session_name", ""),
                active_agent=session.get("active_agent"),
                thinking_mode=session.get("thinking_mode"),
                last_activity=session.get("last_activity", ""),
                last_input=session.get("last_input"),
                last_output=session.get("last_output"),
                initiator_session_id=session.get("initiator_session_id"),
                working_directory=session.get("working_directory"),
            )
        )
    return result


@router.post("/sessions", response_model=dict[str, object])  # guard: loose-dict
async def create_session(request: CreateSessionRequest) -> dict[str, object]:  # guard: loose-dict
    """Create session (local or remote via Redis)."""
    mcp = get_mcp()
    result = await mcp.teleclaude__start_session(
        computer=request.computer,
        project_dir=request.project_dir,
        agent=request.agent,
        thinking_mode=ThinkingMode(request.thinking_mode),
        title=request.title or "Untitled",
        message=request.message,
    )
    return dict(result)  # type: ignore[arg-type]  # TypedDict to dict conversion


@router.delete("/sessions/{session_id}")
async def end_session(session_id: str, computer: str = Query(...)) -> dict[str, object]:  # guard: loose-dict
    """End session."""
    mcp = get_mcp()
    result = await mcp.teleclaude__end_session(
        computer=computer,
        session_id=session_id,
    )
    return dict(result)  # type: ignore[arg-type]  # TypedDict to dict conversion


@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: str, request: SendMessageRequest, computer: str = Query(...)
) -> dict[str, object]:  # guard: loose-dict
    """Send message to session."""
    mcp = get_mcp()
    # Note: send_message returns AsyncIterator, we consume it here
    iterator = mcp.teleclaude__send_message(
        computer=computer,
        session_id=session_id,
        message=request.message,
    )
    result: list[str] = []
    async for chunk in iterator:
        result.append(chunk)
    return {"status": "success", "chunks": result}


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(
    session_id: str,
    computer: str = Query(...),
    tail_chars: int = Query(5000),
) -> dict[str, object]:  # guard: loose-dict
    """Get session transcript."""
    mcp = get_mcp()
    result = await mcp.teleclaude__get_session_data(
        computer=computer,
        session_id=session_id,
        tail_chars=tail_chars,
    )
    return dict(result)


@router.get("/computers", response_model=list[ComputerResponse])
async def list_computers() -> list[ComputerResponse]:
    """List online computers only."""
    mcp = get_mcp()
    computers = await mcp.teleclaude__list_computers()

    # Filter to online only and convert to response format
    result: list[ComputerResponse] = []
    for comp in computers:
        if comp.get("status") == "online":
            result.append(
                ComputerResponse(
                    name=comp["name"],
                    status=comp["status"],
                    user=comp.get("user"),
                    host=comp.get("host"),
                )
            )
    return result


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(computer: str | None = None) -> list[ProjectResponse]:
    """List projects from all or specific computer."""
    mcp = get_mcp()
    projects = await mcp.teleclaude__list_projects(computer=computer or "local")

    # Convert to response format
    result: list[ProjectResponse] = []
    for project in projects:
        result.append(
            ProjectResponse(
                computer=project.get("computer", "local"),
                name=project.get("name", ""),
                path=project.get("location", ""),
                description=project.get("desc"),
            )
        )
    return result


@router.get("/agents/availability", response_model=dict[str, AgentAvailability])
async def get_agent_availability() -> dict[str, AgentAvailability]:
    """Get agent availability from database."""
    agents = ["claude", "gemini", "codex"]
    result: dict[str, AgentAvailability] = {}

    for agent in agents:
        info = await db.get_agent_availability(agent)
        if info:
            unavail_until = info.get("unavailable_until")
            reason_val = info.get("reason")
            result[agent] = AgentAvailability(
                agent=agent,
                available=bool(info.get("available", True)),
                unavailable_until=str(unavail_until) if unavail_until and unavail_until is not True else None,
                reason=str(reason_val) if reason_val and reason_val is not True else None,
            )
        else:
            # Agent not in DB = available
            result[agent] = AgentAvailability(
                agent=agent,
                available=True,
                unavailable_until=None,
                reason=None,
            )

    return result


@router.get("/projects/{path:path}/todos", response_model=list[TodoResponse])
async def list_todos(path: str, computer: str = Query(...)) -> list[TodoResponse]:  # noqa: ARG001 - computer needed for API consistency
    """List todos from roadmap.md for a project."""
    # Parse todos/roadmap.md at the project path
    roadmap_path = Path(path) / "todos" / "roadmap.md"

    if not roadmap_path.exists():
        return []

    content = roadmap_path.read_text()
    todos: list[TodoResponse] = []

    # Pattern for todo line: - [ ] slug-name or - [.] slug-name or - [>] slug-name
    pattern = re.compile(r"^-\s+\[([ .>])\]\s+(\S+)", re.MULTILINE)

    # Status marker mapping
    status_map = {
        " ": "pending",
        ".": "ready",
        ">": "in_progress",
    }

    lines = content.split("\n")
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            status_char = match.group(1)
            slug = match.group(2)

            # Extract description (next indented lines)
            description = ""
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if next_line.startswith("      "):  # 6 spaces = indented
                    description += next_line.strip() + " "
                elif next_line.strip() == "":
                    continue
                else:
                    break

            # Check for requirements.md and implementation-plan.md
            todos_dir = Path(path) / "todos" / slug
            has_requirements = (todos_dir / "requirements.md").exists()
            has_impl_plan = (todos_dir / "implementation-plan.md").exists()

            todos.append(
                TodoResponse(
                    slug=slug,
                    status=status_map.get(status_char, "pending"),
                    description=description.strip() or None,
                    has_requirements=has_requirements,
                    has_impl_plan=has_impl_plan,
                )
            )

    return todos
