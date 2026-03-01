# Implementation Plan: default-agent-resolution

## Overview

Three-phase approach: add config field with validation, create single resolver, replace all call sites, fix launcher pinning. Each phase is independently committable.

## Phase 1: Config schema + core resolver

### Task 1.1: Add `default_agent` to config schema

**File(s):** `teleclaude/config/__init__.py`

- [ ] Add `default_agent: str` field to `Config` dataclass (between `agents` and `terminal`)
- [ ] In `_require_agents_section`, extract `agents_raw.pop("default")` before agent iteration (so it doesn't fail the unknown-key check)
- [ ] Validate: must be a string, must be in `AGENT_PROTOCOL` keys
- [ ] After building `agents_registry`: validate the default agent is enabled
- [ ] Pass `default_agent` to `Config(...)` constructor
- [ ] Raise `ValueError` with clear message if missing, unknown, or disabled

### Task 1.2: Create `get_default_agent()` in core

**File(s):** `teleclaude/core/agents.py`

- [ ] Add function:
  ```python
  def get_default_agent() -> str:
      """Return the config-declared default agent name.

      Raises ValueError if the default agent is not enabled.
      """
      return assert_agent_enabled(config.default_agent)
  ```
- [ ] Export from module

### Task 1.3: Add config.yml `agents.default` field

**File(s):** Project config files (config.yml, example configs)

- [ ] Add `default: claude` under `agents:` in all config files

---

## Phase 2: Replace all call sites

### Task 2.1: Discord adapter — delete `_default_agent` property, replace all hardcoded agents

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Delete `_default_agent` property (lines 164-170)
- [ ] Line 2459: replace `auto_command = "agent claude"` with `auto_command = f"agent {get_default_agent()}"`
- [ ] Line 2464: replace `auto_command = f"agent {self._default_agent}"` with `auto_command = f"agent {get_default_agent()}"`
- [ ] Line 1857: replace `auto_command="agent claude"` with `auto_command=f"agent {get_default_agent()}"`
- [ ] Line 1932: replace `auto_command="agent claude"` with `auto_command=f"agent {get_default_agent()}"`
- [ ] Add import: `from teleclaude.core.agents import get_default_agent`

### Task 2.2: Telegram adapter — replace hardcoded agents

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] Line 434: replace `auto_command="agent claude"` with `auto_command=f"agent {get_default_agent()}"`
- [ ] Line 503: replace `auto_command="agent claude"` with `auto_command=f"agent {get_default_agent()}"`
- [ ] Add import: `from teleclaude.core.agents import get_default_agent`

### Task 2.3: WhatsApp handler — replace hardcoded agent

**File(s):** `teleclaude/hooks/whatsapp_handler.py`

- [ ] Line 46: replace `auto_command="agent claude"` with `auto_command=f"agent {get_default_agent()}"`
- [ ] Add import: `from teleclaude.core.agents import get_default_agent`

### Task 2.4: Command mapper — delete `_default_agent_name()`, use resolver

**File(s):** `teleclaude/core/command_mapper.py`

- [ ] Delete `_default_agent_name()` function (lines 41-45)
- [ ] Replace all 3 call sites (`_default_agent_name()`) with `get_default_agent()`
- [ ] Add import: `from teleclaude.core.agents import get_default_agent`

### Task 2.5: API server — replace inline resolution (two sites)

**File(s):** `teleclaude/api_server.py`

- [ ] Site 1 (line 566): Replace the `enabled_agents[0]` fallback in `_resolve_enabled_agent(None)` with `get_default_agent()`
- [ ] Remove the `get_enabled_agents()` call and empty-check inside (lines 560-565) — `get_default_agent()` handles this
- [ ] Site 2 (line 1203): Replace `effective_agent = enabled_agents[0]` in the sessions-run endpoint with `get_default_agent()`
- [ ] Remove the `get_enabled_agents()` call and empty-check (lines 1197-1202) — same pattern
- [ ] Add import: `from teleclaude.core.agents import get_default_agent`

### Task 2.6: Checkpoint dispatch + agent coordinator — replace enum defaults

**File(s):** `teleclaude/core/checkpoint_dispatch.py`, `teleclaude/core/agent_coordinator.py`

- [ ] `checkpoint_dispatch.py` line 36: change `default_agent: AgentName = AgentName.CLAUDE` to no default — make callers pass it explicitly
- [ ] `agent_coordinator.py` line 1612: pass `default_agent=AgentName.from_str(get_default_agent())`
- [ ] `command_handlers.py` line 1939: already passes `target_agent` — no change needed
- [ ] Add import where needed: `from teleclaude.core.agents import get_default_agent`

### Task 2.7: Checkpoint context dataclass — replace default field

**File(s):** `teleclaude/hooks/checkpoint.py`

- [ ] Line 77: change `agent_name: AgentName = AgentName.CLAUDE` in `CheckpointContext` dataclass to require explicit value (remove default)
- [ ] Verify all callers of `CheckpointContext` pass `agent_name` explicitly; fix any that don't

### Task 2.8: Receiver hook — replace silent fallback

**File(s):** `teleclaude/hooks/receiver.py`

- [ ] Line 190: replace `agent_enum = AgentName.CLAUDE` fallback with `agent_enum = AgentName.from_str(get_default_agent())`
- [ ] Or: let the ValueError propagate (fail-fast) — decide based on whether a checkpoint for an unknown agent should proceed or abort
- [ ] Add import: `from teleclaude.core.agents import get_default_agent`

### Scoping note: transcript parser fallbacks (deferred)

The following sites use `AgentName.CLAUDE` as a parser-selection fallback, not agent-launch resolution:

- `api_server.py:1109` — parser selection when `session.active_agent` is unknown
- `api/streaming.py:125` — `_get_agent_name()` returns CLAUDE for unknown agents

These are NOT default agent resolution — they select a transcript parser format. Making them fail-fast would break transcript display for sessions with unknown agent types. **Deferred** — address separately if the "no fallbacks" rule should extend to parser selection.

---

## Phase 3: Discord launcher fixes

### Task 3.1: Pin launcher thread to forum top

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In `_post_or_update_launcher`, after creating the thread (after line 663), add:
  ```python
  edit_fn = getattr(launcher_thread, "edit", None)
  if callable(edit_fn):
      await self._require_async_callable(edit_fn, label="Discord thread pin-to-forum")(pinned=True)
  ```
- [ ] For existing launcher threads (the update path around line 632), also pin if not already pinned:
  ```python
  if not getattr(launcher_thread, "is_pinned", lambda: False)():
      edit_fn = getattr(launcher_thread, "edit", None)
      if callable(edit_fn):
          await self._require_async_callable(edit_fn, label="Discord thread pin-to-forum")(pinned=True)
  ```

### Task 3.2: Post launchers to all managed forums

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Replace the loop at line 1789:
  ```python
  # Before:
  for forum_id in self._project_forum_map.values():

  # After:
  all_forum_ids: set[int] = set(self._project_forum_map.values())
  if self._help_desk_channel_id:
      all_forum_ids.add(self._help_desk_channel_id)
  if self._all_sessions_channel_id:
      all_forum_ids.add(self._all_sessions_channel_id)
  for forum_id in all_forum_ids:
  ```

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Test `get_default_agent()` returns config value when valid
- [ ] Test `get_default_agent()` raises when default agent is disabled
- [ ] Test config parsing rejects missing `agents.default`
- [ ] Test config parsing rejects unknown agent name in `agents.default`
- [ ] Test config parsing rejects disabled agent as default
- [ ] Verify existing tests still pass with updated config fixtures
- [ ] Run `make test`

### Task 4.2: Quality checks

- [ ] Run `make lint`
- [ ] Grep for remaining `"agent claude"` hardcoded strings (should be zero outside tests/docs)
- [ ] Grep for `enabled_agents[0]` patterns (should be zero)
- [ ] Grep for `AgentName.CLAUDE` used as default parameter (should be zero)

---

## Phase 5: Review readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
