# Implementation Plan: telec TUI

## Overview

Transform `telec` from a SQLite-polling CLI into a rich TUI client using REST API over Unix socket. Single unified project-centric view with AI-to-AI session nesting.

## Phase 1: REST API (Daemon Side)

### 1.1 Create API Module

New file: `teleclaude/api/__init__.py`

```python
"""REST API for telec and other local clients."""

from fastapi import FastAPI

app = FastAPI(title="TeleClaude API", version="1.0.0")
```

### 1.2 API Routes

New file: `teleclaude/api/routes.py`

REST routes are thin wrappers that call existing handlers from `MCPHandlersMixin`.
The handlers already implement Redis-based cross-computer communication.

```python
"""API route definitions - thin wrappers around existing handlers."""

from fastapi import APIRouter
from teleclaude.mcp.handlers import MCPHandlersMixin

router = APIRouter()
handlers = MCPHandlersMixin()  # Or inject via dependency


@router.get("/sessions")
async def list_sessions(computer: str | None = None):
    """List sessions from all computers via Redis."""
    return await handlers._handle_list_sessions({"computer": computer})


@router.post("/sessions")
async def create_session(request: CreateSessionRequest):
    """Create session (local or remote via Redis)."""
    return await handlers._handle_start_session({
        "computer": request.computer,
        "project_dir": request.project_dir,
        "agent": request.agent,
        "thinking_mode": request.thinking_mode,
        "title": request.title,
        "message": request.message,
    })


@router.delete("/sessions/{session_id}")
async def end_session(session_id: str, computer: str):
    """End session."""
    return await handlers._handle_end_session({
        "computer": computer,
        "session_id": session_id,
    })


@router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, request: SendMessageRequest, computer: str):
    """Send message to session."""
    return await handlers._handle_send_message({
        "computer": computer,
        "session_id": session_id,
        "message": request.message,
    })


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: str, computer: str, tail_chars: int = 5000):
    """Get session transcript."""
    return await handlers._handle_get_session_data({
        "computer": computer,
        "session_id": session_id,
        "tail_chars": tail_chars,
    })


@router.get("/computers")
async def list_computers():
    """List online computers only."""
    result = await handlers._handle_list_computers({})
    # Filter to online only
    return [c for c in result if c.get("status") == "online"]


@router.get("/projects")
async def list_projects(computer: str | None = None):
    """List projects from all or specific computer."""
    return await handlers._handle_list_projects({"computer": computer})


@router.get("/agents/availability")
async def get_agent_availability():
    """Get agent availability from database."""
    # Direct DB read
    ...
```

### 1.3 Request/Response Models

New file: `teleclaude/api/models.py`

```python
"""API request/response models."""

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    computer: str
    project_dir: str
    agent: str = "claude"
    thinking_mode: str = "slow"
    title: str | None = None
    message: str


class SendMessageRequest(BaseModel):
    message: str


class SessionResponse(BaseModel):
    session_id: str
    computer: str
    title: str | None
    tmux_session_name: str
    active_agent: str | None
    thinking_mode: str | None
    last_activity: str
    last_input: str | None
    last_output: str | None
    initiator_session_id: str | None  # For AI-to-AI nesting


class ComputerResponse(BaseModel):
    name: str
    status: str  # "online" only (offline filtered out)
    user: str
    host: str


class ProjectResponse(BaseModel):
    computer: str
    name: str
    path: str
    description: str | None


class AgentAvailability(BaseModel):
    agent: str
    available: bool
    unavailable_until: str | None
    reason: str | None
```

### 1.4 Integrate API into Daemon

Update `teleclaude/daemon.py`:

```python
from teleclaude.api import app as api_app

class TeleClaudeDaemon:
    async def start(self):
        # ... existing startup ...

        # Start REST API on Unix socket
        self._api_server = await self._start_api_server()

    async def _start_api_server(self):
        import uvicorn
        config = uvicorn.Config(
            api_app,
            uds="/tmp/teleclaude-api.sock",
            log_level="warning",
        )
        server = uvicorn.Server(config)
        asyncio.create_task(server.serve())
        return server
```

## Phase 2: API Client (telec Side)

### 2.1 Create HTTP Client

New file: `teleclaude/cli/api_client.py`

```python
"""HTTP client for telec TUI."""

import httpx

API_SOCKET = "/tmp/teleclaude-api.sock"
BASE_URL = "http://localhost"


class TelecAPIClient:
    """Async HTTP client for telec."""

    def __init__(self, socket_path: str = API_SOCKET):
        self.socket_path = socket_path
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Connect to API socket."""
        transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url=BASE_URL,
            timeout=5.0,
        )

    async def close(self) -> None:
        """Close connection."""
        if self._client:
            await self._client.aclose()

    async def list_sessions(self, computer: str | None = None) -> list[dict]:
        params = {"computer": computer} if computer else {}
        resp = await self._client.get("/sessions", params=params)
        resp.raise_for_status()
        return resp.json()

    async def list_computers(self) -> list[dict]:
        """Returns only online computers."""
        resp = await self._client.get("/computers")
        resp.raise_for_status()
        return resp.json()

    async def list_projects(self, computer: str | None = None) -> list[dict]:
        params = {"computer": computer} if computer else {}
        resp = await self._client.get("/projects", params=params)
        resp.raise_for_status()
        return resp.json()

    async def create_session(self, **kwargs) -> dict:
        resp = await self._client.post("/sessions", json=kwargs)
        resp.raise_for_status()
        return resp.json()

    async def end_session(self, session_id: str, computer: str) -> bool:
        resp = await self._client.delete(
            f"/sessions/{session_id}",
            params={"computer": computer},
        )
        return resp.status_code == 200

    async def send_message(self, session_id: str, computer: str, message: str) -> bool:
        resp = await self._client.post(
            f"/sessions/{session_id}/message",
            params={"computer": computer},
            json={"message": message},
        )
        return resp.status_code == 200

    async def get_transcript(self, session_id: str, computer: str, tail_chars: int = 5000) -> str:
        resp = await self._client.get(
            f"/sessions/{session_id}/transcript",
            params={"computer": computer, "tail_chars": tail_chars},
        )
        resp.raise_for_status()
        return resp.json().get("transcript", "")

    async def get_agent_availability(self) -> dict[str, dict]:
        resp = await self._client.get("/agents/availability")
        resp.raise_for_status()
        return resp.json()
```

## Phase 3: TUI Framework

### 3.1 Module Structure

```
teleclaude/cli/
├── telec.py              # Entry point (update)
├── api_client.py         # HTTP client (new)
└── tui/                   # TUI components (new)
    ├── __init__.py
    ├── app.py            # Main TUI app
    ├── tree.py           # Project-centric tree builder
    ├── widgets/
    │   ├── __init__.py
    │   ├── footer.py     # Status footer
    │   └── modal.py      # Start session modal
    └── theme.py          # Agent colors and styling
```

### 3.2 Theme and Colors

`teleclaude/cli/tui/theme.py`:

```python
"""Agent colors and styling."""

import curses

# Agent color definitions (initialized after curses.start_color())
AGENT_COLORS = {
    "claude": {"bright": 1, "muted": 2},   # e.g., orange tones
    "gemini": {"bright": 3, "muted": 4},   # e.g., blue tones
    "codex": {"bright": 5, "muted": 6},    # e.g., green tones
}


def init_colors():
    """Initialize curses color pairs."""
    curses.start_color()
    curses.use_default_colors()

    # Define color pairs for each agent
    # Pair 1-2: Claude (bright/muted)
    curses.init_pair(1, curses.COLOR_YELLOW, -1)
    curses.init_pair(2, 172, -1)  # Muted yellow/orange

    # Pair 3-4: Gemini (bright/muted)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, 67, -1)  # Muted cyan

    # Pair 5-6: Codex (bright/muted)
    curses.init_pair(5, curses.COLOR_GREEN, -1)
    curses.init_pair(6, 65, -1)  # Muted green

    # Pair 7: Disabled/unavailable
    curses.init_pair(7, curses.COLOR_WHITE, -1)
```

### 3.3 Tree Builder

`teleclaude/cli/tui/tree.py`:

```python
"""Build project-centric tree from API data."""

from dataclasses import dataclass


@dataclass
class TreeNode:
    """Node in the display tree."""
    type: str  # "computer", "project", "session"
    data: dict
    depth: int
    children: list["TreeNode"]
    parent: "TreeNode | None" = None


def build_tree(computers: list[dict], projects: list[dict], sessions: list[dict]) -> list[TreeNode]:
    """Build hierarchical tree for display.

    Structure: Computer → Project → Session (with AI-to-AI nesting)
    """
    tree = []

    # Index sessions by initiator for nesting
    sessions_by_initiator = {}
    root_sessions = []
    for s in sessions:
        if s.get("initiator_session_id"):
            parent_id = s["initiator_session_id"]
            sessions_by_initiator.setdefault(parent_id, []).append(s)
        else:
            root_sessions.append(s)

    for computer in computers:
        comp_node = TreeNode(
            type="computer",
            data=computer,
            depth=0,
            children=[],
        )

        comp_projects = [p for p in projects if p["computer"] == computer["name"]]
        for project in comp_projects:
            proj_node = TreeNode(
                type="project",
                data=project,
                depth=1,
                children=[],
                parent=comp_node,
            )

            # Get root sessions for this project
            proj_sessions = [
                s for s in root_sessions
                if s["computer"] == computer["name"]
                and s.get("project_dir") == project["path"]
            ]

            for idx, session in enumerate(proj_sessions, 1):
                sess_node = _build_session_node(
                    session, idx, 2, proj_node, sessions_by_initiator
                )
                proj_node.children.append(sess_node)

            comp_node.children.append(proj_node)

        tree.append(comp_node)

    return tree


def _build_session_node(
    session: dict,
    index: int | str,
    depth: int,
    parent: TreeNode,
    sessions_by_initiator: dict,
) -> TreeNode:
    """Recursively build session node with children."""
    node = TreeNode(
        type="session",
        data={**session, "display_index": str(index)},
        depth=depth,
        children=[],
        parent=parent,
    )

    # Add child sessions (AI-to-AI)
    child_sessions = sessions_by_initiator.get(session["session_id"], [])
    for child_idx, child in enumerate(child_sessions, 1):
        child_node = _build_session_node(
            child,
            f"{index}.{child_idx}",
            depth + 1,
            node,
            sessions_by_initiator,
        )
        node.children.append(child_node)

    return node
```

### 3.4 Main TUI App

`teleclaude/cli/tui/app.py`:

```python
"""Main TUI application."""

import asyncio
import curses

from .tree import build_tree, TreeNode
from .widgets.footer import Footer
from .widgets.modal import StartSessionModal
from .theme import init_colors, AGENT_COLORS


class TelecApp:
    """Main TUI application - unified project-centric view."""

    def __init__(self, api_client):
        self.api = api_client
        self.tree: list[TreeNode] = []
        self.flat_items: list[TreeNode] = []  # Flattened for navigation
        self.selected_index = 0
        self.scroll_offset = 0
        self.footer = None
        self.running = True
        self.agent_availability = {}

    async def initialize(self) -> None:
        """Load initial data."""
        await self.api.connect()
        await self.refresh_data()

    async def refresh_data(self) -> None:
        """Refresh all data from API."""
        computers, projects, sessions, availability = await asyncio.gather(
            self.api.list_computers(),
            self.api.list_projects(),
            self.api.list_sessions(),
            self.api.get_agent_availability(),
        )

        self.agent_availability = availability
        self.tree = build_tree(computers, projects, sessions)
        self.flat_items = self._flatten_tree(self.tree)
        self.footer = Footer(self.agent_availability)

    def _flatten_tree(self, nodes: list[TreeNode]) -> list[TreeNode]:
        """Flatten tree for navigation."""
        result = []
        for node in nodes:
            result.append(node)
            result.extend(self._flatten_tree(node.children))
        return result

    def run(self, stdscr) -> None:
        """Main event loop."""
        curses.curs_set(0)
        init_colors()

        while self.running:
            self._render(stdscr)
            key = stdscr.getch()
            self._handle_key(key, stdscr)

    def _handle_key(self, key: int, stdscr) -> None:
        """Handle key press."""
        if key == ord('q'):
            self.running = False
        elif key == curses.KEY_UP:
            self.selected_index = max(0, self.selected_index - 1)
        elif key == curses.KEY_DOWN:
            self.selected_index = min(len(self.flat_items) - 1, self.selected_index + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            self._handle_enter(stdscr)
        elif key == ord('n'):
            self._new_session(stdscr)
        elif key == ord('m'):
            self._send_message(stdscr)
        elif key == ord('k'):
            self._kill_session()
        elif key == ord('t'):
            self._view_transcript(stdscr)
        elif key == ord('r'):
            asyncio.get_event_loop().run_until_complete(self.refresh_data())

    def _handle_enter(self, stdscr) -> None:
        """Handle Enter on selected item."""
        if not self.flat_items:
            return

        item = self.flat_items[self.selected_index]

        if item.type == "session":
            self._attach_session(item.data)
        elif item.type == "project":
            # Open start session modal for this project
            self._start_session_for_project(stdscr, item.data)

    def _attach_session(self, session: dict) -> None:
        """Attach to session (exits TUI temporarily)."""
        self.running = False
        # Return session info for attachment after TUI exits
        self._attach_target = session

    def _start_session_for_project(self, stdscr, project: dict) -> None:
        """Open modal to start session on project."""
        modal = StartSessionModal(
            computer=project["computer"],
            project_path=project["path"],
            api=self.api,
            agent_availability=self.agent_availability,
        )
        result = modal.run(stdscr)
        if result:
            # Session started, refresh
            asyncio.get_event_loop().run_until_complete(self.refresh_data())

    def _render(self, stdscr) -> None:
        """Render the unified view."""
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Reserve space for action bar and footer
        content_height = height - 4

        # Render tree items
        visible_start = self.scroll_offset
        visible_end = min(len(self.flat_items), visible_start + content_height)

        for i, item in enumerate(self.flat_items[visible_start:visible_end]):
            row = i
            is_selected = (visible_start + i) == self.selected_index
            self._render_item(stdscr, row, item, width, is_selected)

        # Render action bar
        action_bar = "[Enter] Attach/Start  [n] New  [m] Message  [k] Kill  [t] Transcript  [r] Refresh"
        stdscr.addstr(height - 3, 0, "-" * width)
        stdscr.addstr(height - 2, 0, action_bar[:width])

        # Render footer
        if self.footer:
            self.footer.render(stdscr, height - 1, width)

        stdscr.refresh()

    def _render_item(self, stdscr, row: int, item: TreeNode, width: int, selected: bool) -> None:
        """Render a single tree item."""
        indent = "  " * item.depth
        attr = curses.A_REVERSE if selected else 0

        if item.type == "computer":
            line = f"{indent}{item.data['name']:<50} {item.data.get('status', 'online')}"
            stdscr.addstr(row, 0, line[:width], attr)

        elif item.type == "project":
            path = item.data.get("path", item.data.get("name", ""))
            sessions_text = "(no sessions)" if not item.children else ""
            line = f"{indent}{path} {sessions_text}"
            stdscr.addstr(row, 0, line[:width], attr)

        elif item.type == "session":
            self._render_session(stdscr, row, item, width, selected)

    def _render_session(self, stdscr, row: int, item: TreeNode, width: int, selected: bool) -> None:
        """Render session with input/output lines."""
        session = item.data
        indent = "  " * item.depth
        agent = session.get("active_agent", "?")
        mode = session.get("thinking_mode", "?")
        title = session.get("title", "Untitled")[:30]
        idx = session.get("display_index", "?")

        # Get agent colors
        colors = AGENT_COLORS.get(agent, {"bright": 7, "muted": 7})

        # Determine which line is "active" (most recent)
        has_output = bool(session.get("last_output"))

        attr = curses.A_REVERSE if selected else 0

        # Line 1: Identifier
        line1 = f"{indent}[{idx}] {agent}/{mode}  \"{title}\""
        stdscr.addstr(row, 0, line1[:width], attr)

        # Line 2: Input (bright if no output yet, muted if output exists)
        if session.get("last_input"):
            input_color = colors["muted"] if has_output else colors["bright"]
            input_text = session["last_input"][:80]
            line2 = f"{indent}     Input: {input_text}"
            # Note: In real implementation, use curses.color_pair(input_color)
            # stdscr.addstr(row + 1, 0, line2[:width], curses.color_pair(input_color))

        # Line 3: Output (bright, only if exists)
        if has_output:
            output_color = colors["bright"]
            output_text = session["last_output"][:80]
            line3 = f"{indent}     Output: {output_text}"
            # stdscr.addstr(row + 2, 0, line3[:width], curses.color_pair(output_color))
```

### 3.5 Start Session Modal

`teleclaude/cli/tui/widgets/modal.py`:

```python
"""Modal dialog widgets."""

import asyncio
import curses


class StartSessionModal:
    """Modal for starting a new session."""

    AGENTS = ["claude", "gemini", "codex"]
    MODES = ["fast", "slow", "med"]

    def __init__(self, computer: str, project_path: str, api, agent_availability: dict):
        self.computer = computer
        self.project_path = project_path
        self.api = api
        self.agent_availability = agent_availability

        # Find first available agent
        self.selected_agent = 0
        for i, agent in enumerate(self.AGENTS):
            if self._is_agent_available(agent):
                self.selected_agent = i
                break

        self.selected_mode = 1  # default: slow
        self.prompt = ""
        self.current_field = 0  # 0=agent, 1=mode, 2=prompt

    def _is_agent_available(self, agent: str) -> bool:
        """Check if agent is available."""
        info = self.agent_availability.get(agent, {})
        return info.get("available", True)

    def _get_available_agents(self) -> list[int]:
        """Get indices of available agents."""
        return [i for i, a in enumerate(self.AGENTS) if self._is_agent_available(a)]

    def run(self, stdscr) -> dict | None:
        """Run modal event loop. Returns session info or None."""
        while True:
            self._render(stdscr)
            key = stdscr.getch()

            if key == 27:  # Escape
                return None
            elif key in (curses.KEY_ENTER, 10, 13):
                if self.current_field == 2 and self.prompt.strip():
                    return self._start_session()
                elif self.current_field < 2:
                    self.current_field += 1
            elif key == ord('\t'):
                self.current_field = (self.current_field + 1) % 3
            elif key == curses.KEY_UP:
                self.current_field = max(0, self.current_field - 1)
            elif key == curses.KEY_DOWN:
                self.current_field = min(2, self.current_field + 1)
            elif key == curses.KEY_LEFT:
                self._select_prev()
            elif key == curses.KEY_RIGHT:
                self._select_next()
            elif self.current_field == 2:
                self._handle_prompt_key(key)

    def _select_prev(self) -> None:
        """Select previous option, skipping unavailable agents."""
        if self.current_field == 0:
            available = self._get_available_agents()
            if not available:
                return
            try:
                current_pos = available.index(self.selected_agent)
                new_pos = (current_pos - 1) % len(available)
                self.selected_agent = available[new_pos]
            except ValueError:
                self.selected_agent = available[0]
        elif self.current_field == 1:
            self.selected_mode = (self.selected_mode - 1) % len(self.MODES)

    def _select_next(self) -> None:
        """Select next option, skipping unavailable agents."""
        if self.current_field == 0:
            available = self._get_available_agents()
            if not available:
                return
            try:
                current_pos = available.index(self.selected_agent)
                new_pos = (current_pos + 1) % len(available)
                self.selected_agent = available[new_pos]
            except ValueError:
                self.selected_agent = available[0]
        elif self.current_field == 1:
            self.selected_mode = (self.selected_mode + 1) % len(self.MODES)

    def _handle_prompt_key(self, key: int) -> None:
        """Handle key input in prompt field."""
        if key == curses.KEY_BACKSPACE or key == 127:
            self.prompt = self.prompt[:-1]
        elif 32 <= key <= 126:
            self.prompt += chr(key)

    def _start_session(self) -> dict:
        """Start the session via API."""
        agent = self.AGENTS[self.selected_agent]
        mode = self.MODES[self.selected_mode]

        result = asyncio.get_event_loop().run_until_complete(
            self.api.create_session(
                computer=self.computer,
                project_dir=self.project_path,
                agent=agent,
                thinking_mode=mode,
                message=self.prompt,
            )
        )
        return result

    def _render(self, stdscr) -> None:
        """Render the modal."""
        height, width = stdscr.getmaxyx()

        # Modal dimensions
        modal_h, modal_w = 15, 60
        start_y = (height - modal_h) // 2
        start_x = (width - modal_w) // 2

        # Draw border
        for i in range(modal_h):
            stdscr.addstr(start_y + i, start_x, " " * modal_w, curses.A_REVERSE)

        stdscr.addstr(start_y, start_x, "─ Start Session " + "─" * (modal_w - 16))

        # Computer/Project (read-only)
        stdscr.addstr(start_y + 2, start_x + 2, f"Computer: {self.computer}")
        stdscr.addstr(start_y + 3, start_x + 2, f"Project:  {self.project_path[:45]}")

        # Agent selection
        agent_y = start_y + 5
        stdscr.addstr(agent_y, start_x + 2, "Agent:")
        for i, agent in enumerate(self.AGENTS):
            x = start_x + 10 + i * 15
            available = self._is_agent_available(agent)

            if i == self.selected_agent and available:
                marker = "●"
                attr = curses.A_BOLD if self.current_field == 0 else 0
            elif available:
                marker = "○"
                attr = 0
            else:
                # Unavailable - show grayed with countdown
                info = self.agent_availability.get(agent, {})
                until = info.get("unavailable_until", "")
                marker = "░"
                agent = f"{agent} ({until})" if until else agent
                attr = curses.A_DIM

            stdscr.addstr(agent_y, x, f"{marker} {agent}", attr)

        # Mode selection
        mode_y = start_y + 7
        stdscr.addstr(mode_y, start_x + 2, "Mode:")
        for i, mode in enumerate(self.MODES):
            x = start_x + 10 + i * 12
            if i == self.selected_mode:
                marker = "●"
                attr = curses.A_BOLD if self.current_field == 1 else 0
            else:
                marker = "○"
                attr = 0
            stdscr.addstr(mode_y, x, f"{marker} {mode}", attr)

        # Prompt input
        prompt_y = start_y + 9
        stdscr.addstr(prompt_y, start_x + 2, "Prompt:")
        prompt_attr = curses.A_UNDERLINE if self.current_field == 2 else 0
        stdscr.addstr(prompt_y + 1, start_x + 2, self.prompt[:50] + "_", prompt_attr)

        # Actions
        stdscr.addstr(start_y + 12, start_x + 2, "[Enter] Start    [Esc] Cancel")
```

### 3.6 Footer Widget

`teleclaude/cli/tui/widgets/footer.py`:

```python
"""Status footer widget."""

from datetime import datetime


class Footer:
    """Persistent status footer."""

    def __init__(self, agent_availability: dict):
        self.agent_availability = agent_availability
        self.last_refresh = datetime.now()

    def update_availability(self, availability: dict) -> None:
        """Update agent availability."""
        self.agent_availability = availability
        self.last_refresh = datetime.now()

    def render(self, stdscr, row: int, width: int) -> None:
        """Render footer."""
        agent_parts = []
        for agent in ["claude", "gemini", "codex"]:
            info = self.agent_availability.get(agent, {"available": True})
            if info.get("available", True):
                agent_parts.append(f"{agent} ✓")
            else:
                until = info.get("unavailable_until")
                countdown = self._format_countdown(until) if until else "?"
                agent_parts.append(f"{agent} ✗ ({countdown})")

        agents_str = "Agents: " + "  ".join(agent_parts)

        elapsed = (datetime.now() - self.last_refresh).seconds
        refresh_str = f"Last: {elapsed}s ago"

        footer = f"{agents_str} │ {refresh_str}"
        stdscr.addstr(row, 0, footer[:width])

    def _format_countdown(self, until: str) -> str:
        """Format countdown string from ISO timestamp."""
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            now = datetime.now(until_dt.tzinfo)
            delta = until_dt - now
            if delta.total_seconds() <= 0:
                return "soon"
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        except (ValueError, AttributeError):
            return "?"
```

## Phase 4: Entry Point

### 4.1 Update telec.py

```python
"""telec: TUI client for TeleClaude."""

import asyncio
import curses
import os
import subprocess
import sys

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.tui.app import TelecApp


def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0].startswith("/"):
        _handle_cli_command(argv)
        return

    asyncio.run(_run_tui())


async def _run_tui() -> None:
    """Run TUI application."""
    api = TelecAPIClient()
    app = TelecApp(api)

    try:
        await app.initialize()
        curses.wrapper(app.run)

        # After TUI exits, check if we need to attach
        if hasattr(app, "_attach_target"):
            _attach_to_session(app._attach_target)
    finally:
        await api.close()


def _attach_to_session(session: dict) -> None:
    """Attach to session after TUI exits."""
    tmux_name = session.get("tmux_session_name")
    computer = session.get("computer")

    if computer == os.uname().nodename or computer == "local":
        # Local session
        subprocess.run(["tmux", "attach", "-t", tmux_name])
    else:
        # Remote session - need SSH
        # Get computer info from session or look up
        user = session.get("user", "morriz")
        host = session.get("host", computer)
        subprocess.run(["ssh", "-t", f"{user}@{host}", f"tmux attach -t {tmux_name}"])


def _handle_cli_command(argv: list[str]) -> None:
    """Handle CLI shortcuts like /list, /claude, etc."""
    cmd = argv[0].lstrip("/")
    args = argv[1:]

    api = TelecAPIClient()

    if cmd == "list":
        asyncio.run(_list_sessions(api))
    elif cmd in ("claude", "gemini", "codex"):
        mode = args[0] if args else "slow"
        prompt = " ".join(args[1:]) if len(args) > 1 else None
        asyncio.run(_quick_start(api, cmd, mode, prompt))


async def _list_sessions(api: TelecAPIClient) -> None:
    """List sessions to stdout."""
    await api.connect()
    sessions = await api.list_sessions()
    for s in sessions:
        print(f"{s['computer']}:{s.get('display_index', '?')} {s.get('active_agent')}/{s.get('thinking_mode')} - {s.get('title', 'Untitled')}")
    await api.close()


async def _quick_start(api: TelecAPIClient, agent: str, mode: str, prompt: str | None) -> None:
    """Quick start a session."""
    await api.connect()
    # Use current directory as project
    project_dir = os.getcwd()
    computer = "local"

    if not prompt:
        print("Error: prompt required")
        return

    result = await api.create_session(
        computer=computer,
        project_dir=project_dir,
        agent=agent,
        thinking_mode=mode,
        message=prompt,
    )

    if result.get("tmux_session_name"):
        await api.close()
        subprocess.run(["tmux", "attach", "-t", result["tmux_session_name"]])
    else:
        print(f"Error: {result}")
        await api.close()
```

## Phase 5: Cleanup

After telec TUI is stable:

1. **Remove from daemon.py:**
   - `_terminal_outbox_worker()` method
   - Related helper methods
   - Task creation/cancellation

2. **Remove from db.py:**
   - `fetch_terminal_outbox_batch()`
   - `claim_terminal_outbox()`
   - `mark_terminal_outbox_delivered()`
   - `mark_terminal_outbox_failed()`

3. **Remove from schema.sql:**
   - `terminal_outbox` table

4. **Remove from telec.py (old):**
   - SQLite outbox functions

## Testing Plan

### Unit Tests

- `tests/unit/test_api_routes.py` - API endpoint logic
- `tests/unit/test_api_client.py` - HTTP client methods
- `tests/unit/test_tui_tree.py` - Tree building and AI-to-AI nesting
- `tests/unit/test_tui_modal.py` - Modal behavior, unavailable agent handling

### Integration Tests

- `tests/integration/test_telec_api.py` - Full API flow

### Manual Testing

1. Start daemon, verify API socket created
2. `curl --unix-socket /tmp/teleclaude-api.sock http://localhost/sessions`
3. Launch telec, verify unified tree renders
4. Navigate with arrow keys
5. Verify AI-to-AI sessions are nested correctly
6. Verify color coding (bright = last activity)
7. Start session from project (Enter on empty project)
8. Verify unavailable agents are grayed out and not selectable
9. Attach to local/remote sessions
10. Send message, kill session
11. Verify footer shows agent status
12. Test CLI shortcuts: `telec /list`, `telec /claude slow "hello"`

## Checklist

### Phase 1: REST API
- [ ] Create `teleclaude/api/__init__.py`
- [ ] Create `teleclaude/api/routes.py`
- [ ] Create `teleclaude/api/models.py`
- [ ] Integrate uvicorn into daemon startup
- [ ] Test API with curl

### Phase 2: API Client
- [ ] Create `teleclaude/cli/api_client.py`
- [ ] Test client connectivity

### Phase 3: TUI
- [ ] Create `teleclaude/cli/tui/` structure
- [ ] Create `teleclaude/cli/tui/theme.py` with agent colors
- [ ] Create `teleclaude/cli/tui/tree.py` with AI-to-AI nesting
- [ ] Implement `TelecApp` main loop
- [ ] Implement unified tree view rendering
- [ ] Implement color coding (bright/muted based on last activity)
- [ ] Implement `StartSessionModal` with unavailable agent handling
- [ ] Implement `Footer` widget

### Phase 4: Entry Point
- [ ] Update `telec.py` with TUI and CLI shortcuts

### Phase 5: Cleanup
- [ ] Remove terminal_outbox code
- [ ] Update tests
- [ ] Update AGENTS.md if needed
