# Implementation Plan: telegram-callback-payload-migration

## Overview

Replace hardcoded per-agent callback action enums and maps with a generic, `AgentName`-derived
pattern. Two-separator format `action:agent:arg` replaces per-agent abbreviations. Legacy
payloads are parsed via a static fallback map. Heartbeat keyboard becomes data-driven.

## Phase 1: Core Changes

### Task 1.1: New callback format and action enum

**File(s):** `teleclaude/adapters/telegram/callback_handlers.py`

- [ ] Reduce `CallbackAction` enum to generic actions:
  - `AGENT_SELECT = "asel"` (was `CLAUDE_SELECT`, `GEMINI_SELECT`, `CODEX_SELECT`)
  - `AGENT_RESUME_SELECT = "arsel"` (was `CLAUDE_RESUME_SELECT`, etc.)
  - `AGENT_START = "as"` (was `CLAUDE_START`, `GEMINI_START`, `CODEX_START`)
  - `AGENT_RESUME_START = "ars"` (was `CLAUDE_RESUME_START`, etc.)
  - Keep `DOWNLOAD_FULL`, `SESSION_SELECT`, `SESSION_START`, `CANCEL` unchanged.
- [ ] Remove the old per-agent enum values.
- [ ] Update `AGENT_SELECT_ACTIONS` and `AGENT_START_ACTIONS` sets to use new enums.

### Task 1.2: Legacy payload fallback map

**File(s):** `teleclaude/adapters/telegram/callback_handlers.py`

- [ ] Add `LEGACY_ACTION_MAP: dict[str, tuple[str, str]]` that maps old action prefixes to
  `(canonical_action, agent_name)` tuples:
  ```python
  LEGACY_ACTION_MAP = {
      "csel": ("asel", "claude"),
      "crsel": ("arsel", "claude"),
      "gsel": ("asel", "gemini"),
      "grsel": ("arsel", "gemini"),
      "cxsel": ("asel", "codex"),
      "cxrsel": ("arsel", "codex"),
      "c": ("as", "claude"),
      "cr": ("ars", "claude"),
      "g": ("as", "gemini"),
      "gr": ("ars", "gemini"),
      "cx": ("as", "codex"),
      "cxr": ("ars", "codex"),
  }
  ```
- [ ] In `_handle_callback_query`, after splitting `action_raw`, check `LEGACY_ACTION_MAP`
  first. If matched, rewrite to canonical format (inject agent name into args) before
  dispatching to handlers.

### Task 1.3: Update callback parsing in `_handle_callback_query`

**File(s):** `teleclaude/adapters/telegram/callback_handlers.py`

- [ ] New canonical format uses two colons: `action:agent_name:arg`. Parse accordingly:
  split on `:` with maxsplit=2.
- [ ] For `AGENT_SELECT` and `AGENT_RESUME_SELECT`: extract `agent_name` and pass to
  `_handle_agent_select`.
- [ ] For `AGENT_START` and `AGENT_RESUME_START`: extract `agent_name` and `project_idx`,
  pass to `_handle_agent_start`.
- [ ] Validate `agent_name` against `AgentName.from_str()`. If invalid, log and return.

### Task 1.4: Update `_handle_agent_select`

**File(s):** `teleclaude/adapters/telegram/callback_handlers.py`

- [ ] Change signature to accept `agent_name: str` and `is_resume: bool` instead of raw
  `action: str`.
- [ ] Remove `mode_map` dict. Derive `callback_prefix` and `mode_label` from agent_name
  and is_resume:
  - `callback_prefix = f"{'ars' if is_resume else 'as'}:{agent_name}"`
  - `mode_label = f"{agent_name.title()}{' Resume' if is_resume else ''}"`

### Task 1.5: Update `_handle_agent_start`

**File(s):** `teleclaude/adapters/telegram/callback_handlers.py`

- [ ] Change signature to accept `agent_name: str` and `is_resume: bool` instead of raw
  `action: str`.
- [ ] Remove `event_map` dict. Derive `auto_command` directly:
  - `auto_command = f"agent_resume {agent_name}" if is_resume else f"agent {agent_name}"`
- [ ] Validate agent_name with `AgentName.from_str()` before proceeding.

### Task 1.6: Dynamic heartbeat keyboard

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] Replace hardcoded agent rows in `_build_heartbeat_keyboard` with a loop over
  `get_enabled_agents()`.
- [ ] For each enabled agent, add a row with two buttons:
  - `"🤖 New {agent.title()}"` → `callback_data=f"asel:{agent}:{bot_username}"`
  - `"🔄 Resume {agent.title()}"` → `callback_data=f"arsel:{agent}:{bot_username}"`
- [ ] Keep first row (Tmux Session) unchanged.
- [ ] Agent-specific emoji mapping (optional, keep generic 🤖 if simplicity is preferred).

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Update `tests/unit/test_telegram_menus.py`:
  - Test dynamic keyboard with all agents enabled.
  - Test keyboard with subset of agents enabled.
  - Test new callback_data format in buttons.
- [ ] Add tests for legacy payload parsing:
  - Each old action prefix (`csel`, `gsel`, `cxsel`, `c`, `g`, `cx`, and resume variants)
    maps correctly to canonical format.
- [ ] Add tests for new payload parsing:
  - `asel:claude:bot_username` → agent select for claude.
  - `as:gemini:0` → agent start for gemini project 0.
  - `asel:unknown_agent:bot` → graceful rejection.
- [ ] Test agent start with new payloads creates correct `auto_command`.
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
