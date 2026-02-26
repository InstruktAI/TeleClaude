# Agent Dispatch Guidance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hardcoded agent selection matrices with config-driven guidance text that the orchestrator AI interprets.

**Architecture:** Agent availability and strengths move to `config.yml`. The next-machine composes a guidance text block from enabled agents and embeds it in dispatch instructions. The orchestrator reads the work item and the guidance, then picks agent + thinking mode.

**Tech Stack:** Python, Pydantic (config schema), YAML (config.yml)

---

### Task 1: Add AgentDispatchConfig to config schema

**Files:**

- Modify: `teleclaude/config/schema.py`

**Step 1: Write the failing test**

Create `tests/unit/test_agent_dispatch_config.py`:

```python
"""Tests for agent dispatch config schema."""
import pytest
from teleclaude.config.schema import AgentDispatchConfig

def test_agent_dispatch_config_defaults():
    cfg = AgentDispatchConfig()
    assert cfg.enabled is True
    assert cfg.strengths == ""
    assert cfg.avoid == ""

def test_agent_dispatch_config_explicit():
    cfg = AgentDispatchConfig(
        enabled=True,
        strengths="architecture, oversight",
        avoid="frontend work",
    )
    assert cfg.strengths == "architecture, oversight"
    assert cfg.avoid == "frontend work"

def test_agent_dispatch_config_disabled():
    cfg = AgentDispatchConfig(enabled=False)
    assert cfg.enabled is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_dispatch_config.py -v`
Expected: FAIL — `AgentDispatchConfig` does not exist

**Step 3: Write minimal implementation**

Add to `teleclaude/config/schema.py` after the `BusinessConfig` class:

```python
class AgentDispatchConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    strengths: str = ""
    avoid: str = ""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_dispatch_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add teleclaude/config/schema.py tests/unit/test_agent_dispatch_config.py
git commit -m "feat(config): add AgentDispatchConfig schema"
```

---

### Task 2: Add `enabled` field to AgentConfig and wire config.yml loading

**Files:**

- Modify: `teleclaude/config/__init__.py:123-136` (AgentConfig dataclass)
- Modify: `teleclaude/config/__init__.py:430-447` (\_validate_disallowed_runtime_keys)
- Modify: `teleclaude/config/__init__.py:609-622` (agent registry building in \_build_config)

**Step 1: Write the failing test**

Add to `tests/unit/test_agent_dispatch_config.py`:

```python
from teleclaude.config import AgentConfig

def test_agent_config_has_enabled_and_dispatch():
    """AgentConfig has enabled flag and dispatch fields."""
    cfg = AgentConfig(
        binary="/usr/bin/test",
        profiles={"default": ""},
        session_dir="~/.test",
        log_pattern="*.jsonl",
        model_flags={"slow": "--model x"},
        exec_subcommand="",
        interactive_flag="",
        non_interactive_flag="-p",
        resume_template="{base_cmd} --resume {session_id}",
    )
    # Defaults
    assert cfg.enabled is True
    assert cfg.strengths == ""
    assert cfg.avoid == ""
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_dispatch_config.py::test_agent_config_has_enabled_and_dispatch -v`
Expected: FAIL — `enabled` is not a field on AgentConfig

**Step 3: Implement**

In `teleclaude/config/__init__.py`:

a) Add fields to `AgentConfig` dataclass (after `continue_template`):

```python
    enabled: bool = True
    strengths: str = ""
    avoid: str = ""
```

b) Update `_validate_disallowed_runtime_keys` — remove the `agents` block entirely. The guard was there to prevent binary path overrides; that concern no longer applies since we only read `enabled`/`strengths`/`avoid` from config.yml.

c) Update `_build_config` — after building agents_registry from AGENT_PROTOCOL, overlay config.yml agents section:

```python
    # Overlay agent dispatch config from config.yml
    agents_raw = raw.get("agents", {})
    if isinstance(agents_raw, dict):
        for agent_name, agent_data in agents_raw.items():
            if agent_name in agents_registry and isinstance(agent_data, dict):
                agents_registry[agent_name].enabled = bool(agent_data.get("enabled", True))
                agents_registry[agent_name].strengths = str(agent_data.get("strengths", ""))
                agents_registry[agent_name].avoid = str(agent_data.get("avoid", ""))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_dispatch_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add teleclaude/config/__init__.py tests/unit/test_agent_dispatch_config.py
git commit -m "feat(config): wire agent dispatch config from config.yml"
```

---

### Task 3: Add agents section to config.yml

**Files:**

- Modify: `config.yml`
- Modify: `tests/integration/config.yml` (test fixture)

**Step 1: Add agents section to config.yml**

Add before the `telegram:` section:

```yaml
agents:
  claude:
    enabled: true
    strengths: 'architecture, oversight, review, preparation, general-purpose'
    avoid: 'frontend/UI coding, creative visual work'
  gemini:
    enabled: true
    strengths: 'frontend, UI, creative, greenfield, modern patterns'
    avoid: ''
  codex:
    enabled: true
    strengths: 'backend, thorough coverage, meticulous implementation'
    avoid: ''
```

**Step 2: Add minimal agents section to test config**

Add to `tests/integration/config.yml`:

```yaml
agents:
  claude:
    enabled: true
  gemini:
    enabled: true
  codex:
    enabled: true
```

**Step 3: Run existing tests to verify nothing breaks**

Run: `make test`
Expected: All pass (backwards compatible — agents section is optional with defaults)

**Step 4: Commit**

```bash
git add config.yml tests/integration/config.yml
git commit -m "feat(config): add agents dispatch section to config.yml"
```

---

### Task 4: Write compose_agent_guidance function

**Files:**

- Modify: `teleclaude/core/next_machine/core.py`

**Step 1: Write the failing test**

Add `tests/unit/test_agent_guidance.py`:

```python
"""Tests for agent guidance composition."""
from unittest.mock import AsyncMock
import pytest
from teleclaude.core.next_machine.core import compose_agent_guidance

@pytest.mark.asyncio
async def test_compose_guidance_all_enabled():
    """All agents enabled, none degraded."""
    agents = {
        "claude": {"enabled": True, "strengths": "oversight, review", "avoid": "frontend"},
        "gemini": {"enabled": True, "strengths": "frontend, creative", "avoid": ""},
        "codex": {"enabled": True, "strengths": "backend, thorough", "avoid": ""},
    }
    db = AsyncMock()
    db.get_agent_availability = AsyncMock(return_value=None)
    db.clear_expired_agent_availability = AsyncMock()

    result = await compose_agent_guidance(agents, db)
    assert "claude" in result
    assert "gemini" in result
    assert "codex" in result
    assert "oversight, review" in result
    assert "Avoid: frontend" in result
    assert "Thinking mode" in result

@pytest.mark.asyncio
async def test_compose_guidance_agent_disabled():
    """Disabled agent excluded from guidance."""
    agents = {
        "claude": {"enabled": True, "strengths": "general", "avoid": ""},
        "gemini": {"enabled": False, "strengths": "frontend", "avoid": ""},
    }
    db = AsyncMock()
    db.get_agent_availability = AsyncMock(return_value=None)
    db.clear_expired_agent_availability = AsyncMock()

    result = await compose_agent_guidance(agents, db)
    assert "claude" in result
    assert "gemini" not in result

@pytest.mark.asyncio
async def test_compose_guidance_agent_degraded():
    """Degraded agent noted in guidance."""
    agents = {
        "claude": {"enabled": True, "strengths": "general", "avoid": ""},
        "gemini": {"enabled": True, "strengths": "frontend", "avoid": ""},
    }
    db = AsyncMock()

    async def mock_availability(agent):
        if agent == "gemini":
            return {"available": False, "status": "degraded", "reason": "rate_limited", "unavailable_until": "2026-02-21T14:30:00Z"}
        return None

    db.get_agent_availability = AsyncMock(side_effect=mock_availability)
    db.clear_expired_agent_availability = AsyncMock()

    result = await compose_agent_guidance(agents, db)
    assert "degraded" in result
    assert "rate_limited" in result

@pytest.mark.asyncio
async def test_compose_guidance_single_agent():
    """Only one agent available — guidance is minimal."""
    agents = {
        "claude": {"enabled": True, "strengths": "general", "avoid": ""},
    }
    db = AsyncMock()
    db.get_agent_availability = AsyncMock(return_value=None)
    db.clear_expired_agent_availability = AsyncMock()

    result = await compose_agent_guidance(agents, db)
    assert "claude" in result
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_guidance.py -v`
Expected: FAIL — `compose_agent_guidance` does not exist

**Step 3: Implement compose_agent_guidance**

Add to `teleclaude/core/next_machine/core.py` in the Response Formatters section:

```python
async def compose_agent_guidance(
    agents: dict[str, dict[str, object]],
    db: "Db",
) -> str:
    """Compose agent selection guidance from config and runtime availability.

    Args:
        agents: Dict of agent name -> {"enabled": bool, "strengths": str, "avoid": str}
        db: Database instance for runtime availability checks
    """
    await db.clear_expired_agent_availability()

    lines = []
    for name, cfg in agents.items():
        if not cfg.get("enabled", True):
            continue

        strengths = cfg.get("strengths", "")
        avoid = cfg.get("avoid", "")
        parts = [f"- {name}"]
        if strengths:
            parts.append(f": {strengths}")
        if avoid:
            parts.append(f". Avoid: {avoid}")

        # Check runtime degradation
        availability = await db.get_agent_availability(name)
        if availability and availability.get("status") == "degraded":
            reason = availability.get("reason", "unknown")
            until = availability.get("unavailable_until", "")
            parts.append(f". (degraded: {reason}")
            if until:
                parts.append(f", until {until}")
            parts.append(")")
        elif availability and not availability.get("available", True):
            reason = availability.get("reason", "unknown")
            parts.append(f". (temporarily unavailable: {reason})")

        lines.append("".join(parts))

    if not lines:
        return "ERROR: No agents are enabled in config.yml."

    agent_block = "\n".join(lines)

    return f"""AGENT SELECTION — Choose agent and thinking_mode before dispatching.

Available agents:
{agent_block}

Thinking mode:
- slow: complex/novel work, deep analysis, thorough review
- med: routine implementation, fixes, standard tasks
- fast: mechanical/clerical (finalize, defer, cleanup)

Assess the domain and complexity of this work item, then select agent and thinking_mode."""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_guidance.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add teleclaude/core/next_machine/core.py tests/unit/test_agent_guidance.py
git commit -m "feat(next-machine): add compose_agent_guidance function"
```

---

### Task 5: Modify format_tool_call to use guidance instead of pre-selected agent

**Files:**

- Modify: `teleclaude/core/next_machine/core.py:176-257` (format_tool_call)

**Step 1: Write the failing test**

Add to `tests/unit/test_agent_guidance.py`:

```python
from teleclaude.core.next_machine.core import format_tool_call

def test_format_tool_call_has_guidance_placeholder():
    """format_tool_call includes guidance and agent placeholder."""
    guidance = "Available agents:\n- claude: general"
    result = format_tool_call(
        command="next-build",
        args="my-slug",
        project="/tmp/proj",
        subfolder="trees/my-slug",
        guidance=guidance,
    )
    assert "AGENT SELECTION" in result or "Available agents" in result
    assert 'agent="<' in result or "your choice" in result.lower() or guidance in result
    assert "next-build" in result

def test_format_tool_call_no_hardcoded_agent():
    """format_tool_call does not contain a hardcoded agent value."""
    guidance = "Available agents:\n- claude: general"
    result = format_tool_call(
        command="next-build",
        args="my-slug",
        project="/tmp/proj",
        subfolder="trees/my-slug",
        guidance=guidance,
    )
    # Should not have a literal agent="claude" or agent="gemini" etc.
    assert 'agent="claude"' not in result
    assert 'agent="gemini"' not in result
    assert 'agent="codex"' not in result
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_agent_guidance.py::test_format_tool_call_has_guidance_placeholder -v`
Expected: FAIL — `format_tool_call` still expects `agent` and `thinking_mode` params

**Step 3: Rewrite format_tool_call**

Replace `agent` and `thinking_mode` parameters with `guidance: str`. Change the DISPATCH step to include the guidance block and use placeholders:

```python
def format_tool_call(
    command: str,
    args: str,
    project: str,
    subfolder: str,
    guidance: str,
    note: str = "",
    next_call: str = "",
    completion_args: str | None = None,
) -> str:
    """Format a literal tool call for the orchestrator to execute."""
    raw_command = command.lstrip("/")
    formatted_command = f"/{raw_command}"

    post_completion = POST_COMPLETION.get(command, "")
    if post_completion:
        next_call_display = next_call.strip()
        if next_call_display and PAREN_OPEN not in next_call_display:
            next_call_display = f"{next_call_display}()"
        completion_value = completion_args if completion_args is not None else args
        post_completion = post_completion.format(args=completion_value, next_call=next_call_display)

    result = f"""IMPORTANT: This output is an execution script. Follow it verbatim.

Execute these steps in order (FOLLOW TO THE LETTER!):

STEP 1 - SELECT AGENT:
{guidance}

STEP 2 - DISPATCH:
telec sessions run(
  computer="local",
  command="{formatted_command}",
  args="{args}",
  project="{project}",
  agent="<your selection>",
  thinking_mode="<your selection>",
  subfolder="{subfolder}"
)
Save the returned session_id.

STEP 3 - START BACKGROUND TIMER:
Bash(command="sleep 300", run_in_background=true)
Save the returned task_id.

STEP 4 - WAIT:
Tell the user: "Dispatched session <session_id>. Waiting for completion."
Do NOT call any more tools UNTIL one of the events below fires.
When an event fires, you MUST immediately act on it — do NOT wait for user input.

WHAT HAPPENS NEXT (one of these will occur):

A) NOTIFICATION ARRIVES (worker completed):
   - The timer is now irrelevant (let it expire or ignore it)
   - Follow WHEN WORKER COMPLETES below

B) TIMER COMPLETES (no notification after 5 minutes):
   THIS IS YOUR ACTIVATION TRIGGER. You MUST act immediately:
   - Check on the session: telec sessions tail(computer="local", session_id="<session_id>", tail_chars=2000)
   - If still running: reset timer (sleep 300, run_in_background=true) and WAIT again
   - If completed/idle: follow WHEN WORKER COMPLETES below
   - If stuck/errored: intervene or escalate to user
   Do NOT stop after checking — either reset the timer or execute completion steps.

C) YOU SEND ANOTHER MESSAGE TO THE AGENT BECAUSE IT NEEDS FEEDBACK OR HELP:
   - Cancel the old timer: KillShell(shell_id=<task_id>)
   - Start a new 5-minute timer: Bash(command="sleep 300", run_in_background=true)
   - Save the new task_id for the reset timer

{post_completion}

ORCHESTRATION PRINCIPLE: Guide process, don't dictate implementation.
You are an orchestrator, not a micromanager. Workers have full autonomy.
- NEVER run tests, lint, or make in/targeting worktrees
- NEVER edit or commit files in worktrees
- NEVER cd into worktrees — stay in the main repo root
- ALWAYS end the worker session when its step completes — no exceptions
- Trust the process gates (pre-commit hooks, mark_phase clerical checks)
- If mark_phase rejects, the state machine routes to the fix — do NOT fix it yourself"""
    if note:
        result += f"\n\nNOTE: {note}"
    return result
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_guidance.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add teleclaude/core/next_machine/core.py tests/unit/test_agent_guidance.py
git commit -m "refactor(next-machine): format_tool_call uses guidance instead of hardcoded agent"
```

---

### Task 6: Update all call sites — delete matrices and wire guidance

**Files:**

- Modify: `teleclaude/core/next_machine/core.py` (multiple locations)

This is the big integration task. All `_pick_agent` / `get_available_agent` call sites become `compose_agent_guidance` calls, and `format_tool_call` calls drop `agent`/`thinking_mode`.

**Step 1: Delete the old machinery**

Remove from `core.py`:

- `PREPARE_FALLBACK` dict (lines 70-76)
- `WORK_FALLBACK` dict (lines 78-104)
- `NO_SELECTABLE_AGENTS_PATTERN` regex (line 67)
- `_extract_no_selectable_task_type` function (lines 268-270)
- `format_agent_selection_error` function (lines 273-282)
- `get_available_agent` function (lines 1256-1308)

**Step 2: Add config access to next_work and next_prepare**

Both functions need to read agent dispatch config. Import config at the top of the function (same pattern as handlers.py):

```python
from teleclaude.config import config as app_config
```

Build the agents dict from config:

```python
agents_dispatch = {
    name: {"enabled": ac.enabled, "strengths": ac.strengths, "avoid": ac.avoid}
    for name, ac in app_config.agents.items()
}
```

**Step 3: Replace \_pick_agent in next_work**

The inner `_pick_agent` function (lines 2023-2030) and all its call sites become:

```python
guidance = await compose_agent_guidance(agents_dispatch, db)
```

Every `format_tool_call(... agent=agent, thinking_mode=mode ...)` becomes `format_tool_call(... guidance=guidance ...)`.

The error handling for "no selectable agents" changes: if `compose_agent_guidance` returns an error string (starts with "ERROR:"), return it directly.

Affected call sites in `next_work`:

- Line 2144-2156: build dispatch
- Line 2162-2174: fix dispatch
- Line 2189-2202: review dispatch
- Line 2206-2218: defer dispatch
- Line 2227-2239: finalize dispatch

Affected call sites in `next_prepare`:

- Lines 1833, 1866, 1891, 1918, 1937, 1967: prepare dispatches

**Step 4: Run full test suite**

Run: `make test`

Fix any test that was mocking `get_available_agent` — the tests in `test_next_machine_breakdown.py` (line 186), `test_next_machine_state_deps.py` (line 514), and `test_next_machine_deferral.py` (lines 100, 142) will need their mocks updated to mock `compose_agent_guidance` instead.

**Step 5: Commit**

```bash
git add teleclaude/core/next_machine/core.py tests/
git commit -m "refactor(next-machine): replace agent selection matrices with composed guidance"
```

---

### Task 7: Update tests that mock the old agent selection

**Files:**

- Modify: `tests/unit/test_next_machine_breakdown.py`
- Modify: `tests/unit/test_next_machine_state_deps.py`
- Modify: `tests/unit/core/test_next_machine_deferral.py`

**Step 1: Update test_next_machine_breakdown.py**

Remove `test_get_available_agent_skips_degraded` test (line 186) — the function no longer exists. The behavior is now tested via `test_compose_guidance_agent_degraded` in test_agent_guidance.py.

Remove imports of `WORK_FALLBACK` and `get_available_agent`.

**Step 2: Update test_next_machine_state_deps.py**

Change the mock at line 514 from:

```python
"teleclaude.core.next_machine.core.get_available_agent"
```

to:

```python
"teleclaude.core.next_machine.core.compose_agent_guidance"
```

The mock should return a guidance string instead of a (agent, mode) tuple.

**Step 3: Update test_next_machine_deferral.py**

Same pattern — change mocks at lines 100 and 142 from `get_available_agent` to `compose_agent_guidance`.

**Step 4: Run all tests**

Run: `make test`
Expected: All pass

**Step 5: Commit**

```bash
git add tests/unit/
git commit -m "test: update next-machine tests for guidance-based dispatch"
```

---

### Task 8: Update the teleclaude-config doc snippet

**Files:**

- Modify: `docs/project/spec/teleclaude-config.md`

**Step 1: Add agents section to the spec**

Add to the `config_keys` in the machine-readable surface:

```yaml
agents:
  claude:
    enabled: boolean
    strengths: string
    avoid: string
  gemini:
    enabled: boolean
    strengths: string
    avoid: string
  codex:
    enabled: boolean
    strengths: string
    avoid: string
```

Add a clarification section:

```markdown
## Configuration Files

- `config.yml` — Per-machine application config: computer identity, agents, services, remotes.
- `teleclaude.yml` — Per-project runtime config: project name, jobs, business domains.
```

**Step 2: Commit**

```bash
git add docs/project/spec/teleclaude-config.md
git commit -m "docs: document agents config section and config file distinction"
```

---

### Task 9: Clean up agent_cli.\_pick_agent binary detection

**Files:**

- Modify: `teleclaude/helpers/agent_cli.py:175-220`

**Step 1: Simplify \_pick_agent in agent_cli.py**

This is the standalone agent picker used by jobs and interactive CLI (not the next-machine). It currently does binary detection + DB checks. Update it to also respect `config.agents[name].enabled` — if an agent is disabled in config, skip it even if the binary exists.

**Step 2: Run tests**

Run: `pytest tests/unit/test_agent_cli.py -v && pytest tests/unit/test_daemon_independent_jobs.py -v`
Expected: All pass

**Step 3: Commit**

```bash
git add teleclaude/helpers/agent_cli.py
git commit -m "refactor(agent-cli): respect config.agents.enabled in standalone picker"
```

---

### Task 10: Update next-machine design doc snippet

**Files:**

- Modify: `docs/project/design/architecture/next-machine.md`

**Step 1: Update the design doc**

Remove references to fallback matrices. Update the Worker Dispatch Pattern table and the agent selection description to reflect guidance-based dispatch. Update the "No Selectable Agents" failure mode.

**Step 2: Commit**

```bash
git add docs/project/design/architecture/next-machine.md
git commit -m "docs: update next-machine design for guidance-based agent dispatch"
```
