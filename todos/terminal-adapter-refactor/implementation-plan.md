# Implementation Plan: REST Adapter Refactor

## Overview

Refactor the terminal adapter into a proper REST adapter that routes through AdapterClient like all other adapters. Add resume commands for cross-computer session discovery.

## Phases

### Phase 1: RESTAdapter Foundation
Create the REST adapter, absorb API code, route through AdapterClient.

### Phase 2: Resume Commands
Add `/agent_resume`, `/claude_resume`, `/gemini_resume`, `/codex_resume` handlers.

### Phase 3: CLI & TUI Integration
Update telec CLI to use REST API and add TUI auto-focus on resume.

---

## Phase 1: RESTAdapter Foundation

### Task 1.1: Create RESTAdapter skeleton
**File**: `teleclaude/adapters/rest_adapter.py` (NEW)

```python
class RESTAdapter(BaseAdapter):
    ADAPTER_KEY = "rest"

    def __init__(self, client: AdapterClient):
        self.client = client
        self.app = FastAPI()
        self._setup_routes()

    async def start(self) -> None:
        # Start uvicorn on Unix socket

    async def stop(self) -> None:
        # Shutdown server
```

- Extend `BaseAdapter` (NOT UiAdapter)
- Implement all abstract methods (most are no-ops like current TerminalAdapter)
- Add FastAPI app with routes

### Task 1.2: Move API models
**From**: `teleclaude/api/models.py`
**To**: `teleclaude/adapters/rest_models.py`

- Move all Pydantic models
- Update imports

### Task 1.3: Absorb routes into RESTAdapter
**From**: `teleclaude/api/routes.py`
**Into**: `teleclaude/adapters/rest_adapter.py`

Routes to migrate:
- `GET /sessions` → list sessions
- `POST /sessions` → create session
- `DELETE /sessions/{id}` → end session
- `POST /sessions/{id}/message` → send message
- `GET /sessions/{id}/transcript` → get session data
- `GET /computers` → list computers
- `GET /projects` → list projects
- `GET /agents/availability` → agent availability
- `GET /projects/{path}/todos` → list todos

**Key change**: Routes call `self.client.handle_event()` instead of MCP handlers directly.

### Task 1.4: Route through AdapterClient
For each endpoint, convert HTTP request to AdapterClient event:

```python
@self.app.post("/sessions")
async def create_session(request: CreateSessionRequest):
    result = await self.client.handle_event(
        event_type="command",
        payload={
            "command": "new_session",
            "args": {
                "computer": request.computer,
                "project_dir": request.project_dir,
                ...
            }
        },
        metadata=MessageMetadata(adapter_type="rest"),
    )
    return result
```

### Task 1.5: Update daemon to use RESTAdapter
**File**: `teleclaude/daemon.py`

- Remove `api_server_task` and `_run_api_server()`
- Add RESTAdapter to adapter initialization
- Start RESTAdapter like other adapters via `adapter.start()`

### Task 1.6: Delete old API code
**Delete**:
- `teleclaude/api/routes.py`
- `teleclaude/api/server.py`
- `teleclaude/api/__init__.py`
- `teleclaude/adapters/terminal_adapter.py`

### Task 1.7: Update imports
**Files**: Any file importing from `teleclaude.api` or `terminal_adapter`

- Update to use `rest_adapter` and `rest_models`

### Task 1.8: Tests for Phase 1
- Unit test: RESTAdapter routes call AdapterClient
- Unit test: Each endpoint returns expected structure
- Integration test: Create session via REST, verify in DB

---

## Phase 2: Resume Commands

### Task 2.1: Add DB method for composite lookup
**File**: `teleclaude/core/db.py`

```python
async def get_session_by_agent_and_native_id(
    self,
    agent: str,
    native_session_id: str
) -> Optional[Session]:
    """Get session by agent type and native session ID."""
    cursor = await self.conn.execute(
        "SELECT * FROM sessions WHERE active_agent = ? AND native_session_id = ?",
        (agent, native_session_id),
    )
    row = await cursor.fetchone()
    return Session.from_dict(dict(row)) if row else None
```

### Task 2.2: Add /agent_resume handler
**File**: `teleclaude/core/command_handlers.py`

```python
async def handle_agent_resume(
    session_id: str,
    adapter_client: AdapterClient,
) -> dict:
    """Resume by TeleClaude session ID."""
    # 1. Check local DB
    session = await db.get_session(session_id)
    if session:
        return _session_info(session, "local")

    # 2. Check remote via list_sessions
    remote_sessions = await adapter_client.list_remote_sessions()
    for computer, sessions in remote_sessions.items():
        for s in sessions:
            if s["session_id"] == session_id:
                return _session_info_from_dict(s, computer)

    raise ValueError(f"Session {session_id} not found")
```

### Task 2.3: Add /{agent}_resume handlers
**File**: `teleclaude/core/command_handlers.py`

```python
async def handle_claude_resume(
    native_session_id: str,
    project_dir: str,
    adapter_client: AdapterClient,
) -> dict:
    """Resume by native Claude session ID."""
    # 1. Check local DB
    session = await db.get_session_by_agent_and_native_id("claude", native_session_id)
    if session:
        return _session_info(session, "local")

    # 2. Check remote sessions
    remote_sessions = await adapter_client.list_remote_sessions()
    for computer, sessions in remote_sessions.items():
        for s in sessions:
            if s.get("active_agent") == "claude" and s.get("native_session_id") == native_session_id:
                return _session_info_from_dict(s, computer)

    # 3. Not found - create new session with --resume
    result = await adapter_client.create_session(
        project_dir=project_dir,
        agent="claude",
        native_session_id=native_session_id,  # Triggers --resume in agent command
    )
    return result
```

Same pattern for `handle_gemini_resume` and `handle_codex_resume`.

### Task 2.4: Register commands in daemon
**File**: `teleclaude/daemon.py`

Add to command dispatch:
- `agent_resume` → `handle_agent_resume`
- `claude_resume` → `handle_claude_resume`
- `gemini_resume` → `handle_gemini_resume`
- `codex_resume` → `handle_codex_resume`

### Task 2.5: Add REST endpoints for resume
**File**: `teleclaude/adapters/rest_adapter.py`

```python
@self.app.post("/commands/agent_resume")
async def agent_resume(request: AgentResumeRequest):
    return await self.client.handle_event(
        event_type="command",
        payload={"command": "agent_resume", "session_id": request.session_id},
        metadata=self._metadata(),
    )

@self.app.post("/commands/claude_resume")
async def claude_resume(request: NativeResumeRequest):
    return await self.client.handle_event(
        event_type="command",
        payload={
            "command": "claude_resume",
            "native_session_id": request.native_id,
            "project_dir": request.project_dir,
        },
        metadata=self._metadata(),
    )
```

### Task 2.6: Tests for Phase 2
- Unit test: `get_session_by_agent_and_native_id` returns correct session
- Unit test: `handle_agent_resume` finds local session
- Unit test: `handle_claude_resume` creates new session when not found
- Integration test: Resume finds remote session (mock Redis)

---

## Phase 3: CLI & TUI Integration

### Task 3.1: Update telec CLI to use REST API
**File**: `teleclaude/cli/telec.py`

Replace any direct MCP calls with REST API calls:

```python
async def resume_session(session_id: str):
    """Resume session by TeleClaude ID."""
    async with httpx.AsyncClient(transport=httpx.HTTPTransport(uds=SOCKET_PATH)) as client:
        response = await client.post(
            "http://localhost/commands/agent_resume",
            json={"session_id": session_id},
        )
        return response.json()
```

### Task 3.2: Handle remote session in telec
**File**: `teleclaude/cli/telec.py`

```python
async def attach_session(session_info: dict):
    """Attach to session, using SSH if remote."""
    computer = session_info["computer"]
    tmux_name = session_info["tmux_session_name"]

    if computer == config.computer.name:
        # Local - direct tmux attach
        subprocess.run(["tmux", "attach", "-t", tmux_name], check=True)
    else:
        # Remote - SSH to computer (comp_info from config)
        comp_info = get_computer_info(computer)
        subprocess.run(
            ["ssh", "-t", f"{comp_info.user}@{comp_info.host}", f"tmux attach -t {tmux_name}"],
            check=True,
        )
```

### Task 3.3: Add resume CLI commands
**File**: `teleclaude/cli/telec.py`

```python
@app.command()
def agent_resume(session_id: str):
    """Resume session by TeleClaude ID."""
    session_info = asyncio.run(resume_by_tc_id(session_id))
    launch_tui_with_focus(session_info)

@app.command()
def claude_resume(native_id: str, project_dir: str = "."):
    """Resume session by native Claude session ID."""
    session_info = asyncio.run(resume_by_native("claude", native_id, project_dir))
    launch_tui_with_focus(session_info)
```

### Task 3.4: TUI auto-focus on resume
**File**: `teleclaude/cli/tui/app.py`

Add parameter to TUI initialization:

```python
class TeleClaudeTUI:
    def __init__(self, focus_session: Optional[dict] = None):
        self.focus_session = focus_session

    async def _after_load(self):
        if self.focus_session:
            # Expand tree to session's project
            await self._expand_to_project(self.focus_session["working_directory"])
            # Select session
            await self._select_session(self.focus_session["session_id"])
            # Open split pane
            await self._open_session_pane(self.focus_session)
```

### Task 3.5: Tests for Phase 3
- Unit test: CLI calls correct REST endpoint for resume
- Unit test: Remote session triggers SSH command
- Manual test: TUI focuses on resumed session

---

## Verification Checklist

After all phases:

- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] telec CLI creates session via REST (not direct MCP)
- [ ] Resume by TeleClaude ID works (local)
- [ ] Resume by TeleClaude ID works (remote)
- [ ] Resume by native session ID creates wrapper when not found
- [ ] Resume by native session ID finds existing wrapper
- [ ] TUI auto-focuses on resumed session
- [ ] Telegram `/agent_resume` works with same handler

## Commit Strategy

- Phase 1: `feat(adapters): replace TerminalAdapter with RESTAdapter`
- Phase 2: `feat(handlers): add resume commands for session discovery`
- Phase 3: `feat(cli): update telec to use REST API with TUI auto-focus`
