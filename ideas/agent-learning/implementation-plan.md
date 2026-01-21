# Agent Learning - Implementation Plan

> **Requirements**: todos/agent-learning/requirements.md
> **Status**: Ready to Implement
> **Created**: 2025-12-17
> **Last Updated**: 2025-12-17 (refined architecture)

## Architecture Principles

1. **Receivers stay DUMB** - Hook receivers only emit events, no business logic
2. **Event bus pattern** - Pub-sub in `core/events.py` for extensibility
3. **Handlers do the work** - Learning module subscribes and handles events
4. **Shared utilities** - LLM CLI wrapper in `teleclaude/utils/` for reuse
5. **Prompts as markdown** - Not Python templates

## Implementation Groups

**IMPORTANT**: Tasks within each group CAN be executed in parallel. Groups must be executed sequentially.

### Group 1: Foundation

_These tasks can run in parallel_

- [ ] **PARALLEL** Add pub-sub mechanics to `teleclaude/core/events.py` (`emit()`, `on()`, `clear()`)
- [ ] **PARALLEL** Create `teleclaude/utils/llm.py` - Shared CLI wrapper for Claude/Gemini/Codex
- [ ] **PARALLEL** Create prompts as markdown files in `teleclaude/learning/prompts/`
- [ ] **PARALLEL** Ensure `tmp/` is in `.gitignore`

### Group 2: Learning Module

_These tasks depend on Group 1_

- [ ] **DEPENDS: Group 1** Create `teleclaude/learning/__init__.py` - Module init, exports
- [ ] **DEPENDS: Group 1** Create `teleclaude/learning/manager.py` - Handlers for user_prompt and stop events

### Group 3: Hook Integration

_These tasks depend on Group 2_

- [ ] **DEPENDS: Group 2** Update `teleclaude/hooks/receiver_claude.py` - Emit events (UserPromptSubmit, Stop)
- [ ] **DEPENDS: Group 2** Update `teleclaude/hooks/receiver_gemini.py` - Emit equivalent events
- [ ] **DEPENDS: Group 2** Update `bin/init/install_hooks.py` - Add UserPromptSubmit to hook maps

### Group 4: Testing

_These tasks can run in parallel_

- [ ] **PARALLEL** Create `tests/unit/test_events_pubsub.py` - Test emit/on mechanics
- [ ] **PARALLEL** Create `tests/unit/test_utils_llm.py` - Test CLI wrapper
- [ ] **PARALLEL** Create `tests/unit/test_learning_manager.py` - Test handlers (mock LLM)
- [ ] **DEPENDS: Group 3** Manual integration test: run session, verify learning flow

### Group 5: Documentation & Polish

_These tasks can run in parallel_

- [ ] **PARALLEL** Update TeleClaude README.md - Add agent-learning feature section
- [ ] **PARALLEL** Create `teleclaude/learning/README.md` - Module documentation
- [ ] **DEPENDS: Group 4** Run `make format && make lint && make test`

### Group 6: Review & Finalize

- [ ] **SEQUENTIAL** Review created → produces `review-findings.md`
- [ ] **SEQUENTIAL** Review feedback handled → fixes applied

### Group 7: Merge & Deploy

**Pre-merge:**

- [ ] **SEQUENTIAL** All tests pass (`make test`)
- [ ] **SEQUENTIAL** All Groups 1-6 complete

**Post-merge:**

- [ ] **SEQUENTIAL** Reinstall hooks on all computers (`python bin/init/install_hooks.py`)
- [ ] **SEQUENTIAL** Restart daemons on all computers (`make restart`)
- [ ] **SEQUENTIAL** Verify hooks fire on test session
- [ ] **SEQUENTIAL** Roadmap item marked complete

## Architecture Flow

```
UserPromptSubmit event (from Claude Code)
    ↓
receiver_claude.py
    ↓
events.emit("user_prompt", {message, project_dir})
    ↓
learning.manager handles event (subscribed via events.on)
    ↓ async, non-blocking
LLM call via teleclaude/utils/llm.py (claude -p ... --model haiku)
    ↓
Append to {project}/tmp/learning-raw.jsonl

Stop event (from Claude Code)
    ↓
receiver_claude.py
    ↓
events.emit("stop", {project_dir})
    ↓
learning.manager handles event
    ↓ sync
LLM call (claude -p ... --model sonnet)
    ↓
Update {project}/LEARNED.md (and/or {subfolder}/AGENTS.md)
    ↓
Regenerate {project}/tmp/known-facts-summary.md
    ↓
Delete tmp/learning-raw.jsonl
```

**Key**: Receivers are dumb. They emit. Handlers subscribe. Clean separation.

## Files to Create

### Modify Existing

| File                                  | Changes                                                                |
| ------------------------------------- | ---------------------------------------------------------------------- |
| `teleclaude/core/events.py`           | Add `emit()`, `on()`, `clear()` functions for pub-sub                  |
| `teleclaude/hooks/receiver_claude.py` | Import events, call `emit("user_prompt", ...)` and `emit("stop", ...)` |
| `teleclaude/hooks/receiver_gemini.py` | Same as receiver_claude.py                                             |
| `bin/init/install_hooks.py`           | Add UserPromptSubmit to `_claude_hook_map()`                           |

### New Files

| File                                        | Purpose                                                                        |
| ------------------------------------------- | ------------------------------------------------------------------------------ |
| `teleclaude/utils/llm.py`                   | `call_llm_sync()`, `call_llm_async()` - CLI wrapper for Claude/Gemini/Codex    |
| `teleclaude/learning/__init__.py`           | Module init, exports `init_learning()`                                         |
| `teleclaude/learning/manager.py`            | `init_learning()` subscribes handlers; `handle_user_prompt()`, `handle_stop()` |
| `teleclaude/learning/prompts/extract.md`    | Stage 1 prompt template (opinion mining)                                       |
| `teleclaude/learning/prompts/synthesize.md` | Stage 2 prompt template (knowledge synthesis)                                  |
| `teleclaude/learning/prompts/bootstrap.md`  | Init prompt template (knowledge extraction)                                    |

### Runtime Files (per project)

| File                                   | Purpose                                                  |
| -------------------------------------- | -------------------------------------------------------- |
| `{project}/LEARNED.md`                 | Project-level learned preferences (visible, capital)     |
| `{project}/tmp/known-facts-summary.md` | Compact summary for Stage 1 filtering                    |
| `{project}/tmp/learning-raw.jsonl`     | Ephemeral raw facts (deleted after Stage 2)              |
| `{project}/{subfolder}/AGENTS.md`      | Module-specific facts (created by Stage 2 when relevant) |

## Implementation Details

### 1. Event Bus Addition to core/events.py

Add to existing file (don't create new):

```python
# Module-level pub-sub
_subscribers: dict[str, list[Callable]] = defaultdict(list)

def on(event: str, callback: Callable[[dict], None]) -> None:
    """Subscribe to an event."""
    _subscribers[event].append(callback)

def emit(event: str, data: dict) -> None:
    """Emit an event to all subscribers."""
    for callback in _subscribers.get(event, []):
        try:
            callback(data)
        except Exception as e:
            logger.error("Event handler error: %s", e)

def clear() -> None:
    """Clear all subscribers (for testing)."""
    _subscribers.clear()
```

### 2. Shared LLM Utility (teleclaude/utils/llm.py)

```python
def call_llm_sync(prompt: str, model: str = "haiku", agent: str = "claude") -> str:
    """Sync LLM call via CLI."""
    # Uses: claude -p "prompt" --model model --output-format text
    # Or: gemini -p "prompt" --model model
    # Or: codex equivalent

async def call_llm_async(prompt: str, model: str = "haiku", agent: str = "claude") -> str:
    """Async LLM call via CLI (non-blocking)."""
    # Uses asyncio subprocess
```

### 3. Learning Manager (teleclaude/learning/manager.py)

```python
def init_learning() -> None:
    """Subscribe learning handlers to events. Call once at startup."""
    from teleclaude.core.events import on
    on("user_prompt", _handle_user_prompt)
    on("stop", _handle_stop)

def _handle_user_prompt(data: dict) -> None:
    """Stage 1: Extract facts async."""
    # Reads prompt from prompts/extract.md
    # Calls call_llm_async with haiku
    # Appends to tmp/learning-raw.jsonl

def _handle_stop(data: dict) -> None:
    """Stage 2: Synthesize learnings sync."""
    # Reads prompt from prompts/synthesize.md
    # Calls call_llm_sync with sonnet
    # Updates LEARNED.md (and/or subfolder AGENTS.md)
    # Regenerates tmp/known-facts-summary.md
    # Deletes tmp/learning-raw.jsonl
```

### 4. Hook Receiver Changes

```python
# In receiver_claude.py main()
from teleclaude.core.events import emit

# After getting event_type and data:
if event_type == "user_prompt_submit":
    emit("user_prompt", {"message": data.get("message", ""), "project_dir": project_dir})
elif event_type == "stop":
    emit("stop", {"project_dir": project_dir})

# Continue with existing MCP forwarding...
```

### 5. Hook Registration

Add to `_claude_hook_map()` in install_hooks.py:

```python
"UserPromptSubmit": {
    "type": "command",
    "command": f"{receiver_script} user_prompt_submit",
},
```

## Success Verification

Before marking complete:

- [ ] Events emit/on work (unit test)
- [ ] LLM CLI wrapper works for claude/gemini (unit test)
- [ ] UserPromptSubmit hook fires and emits event
- [ ] Stop hook fires and emits event
- [ ] Stage 1 extracts facts only when novel
- [ ] tmp/learning-raw.jsonl accumulates during session
- [ ] Stage 2 fires on session stop
- [ ] LEARNED.md (and subfolder AGENTS.md) updated correctly
- [ ] tmp/known-facts-summary.md regenerated
- [ ] tmp/learning-raw.jsonl deleted after Stage 2
- [ ] tmp/ folder is gitignored
- [ ] No latency impact on conversation
- [ ] Works for both Claude and Gemini sessions
- [ ] All tests pass (`make test`)

## Completion

When all Group 7 checkboxes are complete, this item is done.

---

**Usage with /next-work**: Execute groups sequentially, parallelize within groups.
