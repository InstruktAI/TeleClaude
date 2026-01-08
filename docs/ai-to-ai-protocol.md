# AI-to-AI Collaboration Protocol

This document specifies how AI agents delegate work to other AI agents within TeleClaude.

## Core Concepts

### Session Types

| Type                 | Description                             |
| -------------------- | --------------------------------------- |
| **Human session**    | User interacts via Telegram or terminal |
| **AI-to-AI session** | One AI starts another AI via MCP        |

All sessions appear in Telegram with their own topics showing full I/O via UiAdapters.

### Local vs Remote

AI-to-AI sessions can run on the **same computer** or a **different computer**:

| Location   | Computer Parameter       | Transport           |
| ---------- | ------------------------ | ------------------- |
| **Local**  | `computer="local"`       | Direct (no network) |
| **Remote** | `computer="workstation"` | Redis pub/sub       |

## MCP Tools Reference

### Discovery Tools

#### List Computers

Get available computers for delegation:

```python
teleclaude__list_computers()
# Returns: [{"name": "macbook", "status": "online"}, {"name": "workstation", "status": "online"}]
```

#### List Projects

Get projects on a specific computer:

```python
teleclaude__list_projects(computer="workstation")
# Returns: [{"path": "/home/user/myapp", "name": "myapp"}, ...]
```

#### List Sessions

Get active sessions on a computer:

```python
teleclaude__list_sessions(computer="local")
# Returns: [{"session_id": "abc-123", "title": "Feature work", "status": "active"}, ...]
```

### Session Lifecycle

#### Start Session

Start a new AI worker session:

```python
# Local AI-to-AI (same computer)
teleclaude__start_session(
    computer="local",
    project_dir="/path/to/project",
    title="Implement feature X",
    message="Please implement the login form",
    agent="claude"
)

# Remote AI-to-AI (different computer)
teleclaude__start_session(
    computer="workstation",
    project_dir="/home/user/project",
    title="Run tests",
    message="Run the test suite and report failures",
    agent="claude"
)
```

#### Run Agent Command

Start a session with a specific agent slash command:

```python
teleclaude__run_agent_command(
    computer="local",
    project_dir="/path/to/project",
    title="Build feature",
    command="/next-build",
    args="auth-system",
    agent="claude"
)
```

#### Send Message

Send a follow-up message to an existing session:

```python
teleclaude__send_message(
    computer="local",
    session_id="abc-123",
    message="Focus on edge cases in the validation logic"
)
```

#### Get Session Data

Retrieve session output for review:

```python
teleclaude__get_session_data(
    computer="local",
    session_id="abc-123",
    last_n_chars=5000  # Optional: limit output size
)
```

#### Stop Notifications

Unsubscribe from session events without ending it:

```python
teleclaude__stop_notifications(
    computer="local",
    session_id="abc-123"
)
```

#### End Session

Gracefully terminate a session:

```python
teleclaude__end_session(
    computer="local",
    session_id="abc-123"
)
```

### File and Result Sharing

#### Send File

Send a file to a session:

```python
teleclaude__send_file(
    session_id="abc-123",
    file_path="/path/to/requirements.txt",
    caption="Updated requirements"
)
```

#### Send Result

Send structured result data to a session:

```python
teleclaude__send_result(
    session_id="abc-123",
    result="Build completed successfully",
    metadata={"tests_passed": 42, "coverage": "87%"}
)
```

### Deployment

#### Deploy

Deploy code to computers:

```python
# Deploy to all computers
teleclaude__deploy()

# Deploy to specific computers
teleclaude__deploy(computers=["workstation", "server"])
```

### Orchestration Tools

These tools support the architect-builder workflow for managing work items.

#### Next Prepare

Prepare a work item for implementation:

```python
teleclaude__next_prepare(
    slug="auth-system",
    cwd="/path/to/project",
    hitl=True  # Human-in-the-loop for approval
)
```

#### Next Work

Start work on an item (orchestrates the full workflow):

```python
teleclaude__next_work(
    slug="auth-system",
    cwd="/path/to/project"
)
```

#### Mark Phase

Mark a workflow phase as complete:

```python
teleclaude__mark_phase(
    slug="auth-system",
    phase="build",
    status="complete"
)
```

#### Set Dependencies

Define dependencies between work items:

```python
teleclaude__set_dependencies(
    slug="auth-system",
    depends_on=["database-schema", "user-model"]
)
```

#### Mark Agent Unavailable

Mark an agent as temporarily unavailable (rate limits, errors):

```python
teleclaude__mark_agent_unavailable(
    computer="workstation",
    duration_hours=4,
    reason="Rate limit exceeded"
)
```

## Workflow Examples

### Simple Delegation

1. **Master AI**: Calls `teleclaude__start_session(computer="local", ...)`
2. **Worker AI**: Receives initial message and begins work
3. **Master AI**: Receives stop notification with summary when worker completes turn
4. **Master AI**: Reviews summary, optionally sends follow-up via `send_message`
5. **Worker AI**: Continues or completes task
6. **Master AI**: Calls `end_session` when work is done

### Parallel Workers

```python
# Start multiple workers concurrently
session1 = teleclaude__start_session(computer="local", title="Frontend work", ...)
session2 = teleclaude__start_session(computer="workstation", title="Backend work", ...)

# Monitor both via notifications
# Each worker's stop events arrive independently
```

### Long-Running Task with Context Management

1. **Master AI**: Starts worker with complex task
2. **Worker AI**: Works autonomously
3. **Master AI**: Monitors progress via `get_session_data`
4. **Master AI**: When worker nears context limit:
   - Asks worker to document findings
   - Retrieves results with `get_session_data`
   - Ends session with `end_session`
   - Starts fresh session for continued work

### Cross-Computer Deployment Workflow

```python
# 1. Verify computers are online
computers = teleclaude__list_computers()

# 2. Deploy to all
result = teleclaude__deploy()

# 3. Start verification workers on each computer
for computer in computers:
    teleclaude__start_session(
        computer=computer["name"],
        title=f"Verify deployment on {computer['name']}",
        message="Run smoke tests and report status"
    )
```

### Orchestrated Build Pipeline

```python
# 1. Prepare work item
teleclaude__next_prepare(slug="new-feature")

# 2. Start build workflow
teleclaude__next_work(slug="new-feature")

# 3. Worker completes build, master marks phase
teleclaude__mark_phase(slug="new-feature", phase="build", status="complete")

# 4. Continue to next phase
teleclaude__next_work(slug="new-feature")
```

## Automatic Notifications

When you start an AI-to-AI session, you automatically receive notifications when:

- The worker AI completes a turn (stop event with summary)
- The worker needs input

## Telegram Integration

All AI-to-AI sessions create Telegram topics showing:

- Session title with initiator info (e.g., `macbook/claude → local/claude: Implement feature X`)
- AI-generated summaries after each turn
- Stop events when the AI completes
