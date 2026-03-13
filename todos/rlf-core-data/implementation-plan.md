# Implementation Plan: rlf-core-data

## Overview

Convert three large monolithic files into Python packages using the `__init__.py` re-export
pattern. Each package preserves all existing import paths. The `Db` class uses Python mixin
inheritance so each mixin group can reference `self._session()` and other base helpers via
the MRO.

Dependency order for splits: `models` first (no internal core deps), then `command_handlers`
(depends on models), then `db` (depends on both).

---

## Phase 1: Split models.py

### Task 1.1: Create models package skeleton

**File(s):** `teleclaude/core/models/`

- [x] Create `teleclaude/core/models/` directory
- [x] Create `teleclaude/core/models/_types.py` — JsonPrimitive, JsonValue, JsonDict, asdict_exclude_none
- [x] Create `teleclaude/core/models/_context.py` — BaseCommandContext and subclasses, SystemCommandContext
- [x] Create `teleclaude/core/models/_adapter.py` — AdapterType, PeerInfo, adapter metadata classes, SessionAdapterMetadata
- [x] Create `teleclaude/core/models/_session.py` — ChannelMetadata, SessionMetadata, MessageMetadata, enums, Session, Recording
- [x] Create `teleclaude/core/models/_snapshot.py` — ThinkingMode, SessionSnapshot, RedisInboundMessage, StartSessionArgs, RunAgentCommandArgs, AgentStartArgs, AgentResumeArgs, KillArgs, SystemCommandArgs, MessagePayload, ComputerInfo, TodoInfo, ProjectInfo, CommandPayload
- [x] Create `teleclaude/core/models/__init__.py` — re-exports all public names from submodules
- [x] Delete `teleclaude/core/models.py`

---

## Phase 2: Split command_handlers.py

### Task 2.1: Create command_handlers package skeleton

**File(s):** `teleclaude/core/command_handlers/`

- [x] Create `teleclaude/core/command_handlers/` directory
- [x] Create `teleclaude/core/command_handlers/_session.py` — create_session, list_sessions, list_projects, list_projects_with_todos, list_todos, get_session_data, close_session, end_session, get_computer_info
- [x] Create `teleclaude/core/command_handlers/_message.py` — process_message, deliver_inbound, handle_voice, handle_file, _session_message_delivery_available, _wait_for_session_ready
- [x] Create `teleclaude/core/command_handlers/_keys.py` — _execute_control_key, _ensure_tmux_for_headless, keys, cancel_command, kill_command, escape_command, ctrl_command, tab_command, shift_tab_command, backspace_command, enter_command, arrow_key_command
- [x] Create `teleclaude/core/command_handlers/_agent.py` — start_agent, resume_agent, agent_restart, run_agent_command, _get_session_profile
- [x] Create `teleclaude/core/command_handlers/__init__.py` — re-exports all public names + with_session, EndSessionHandlerResult, SessionDataPayload
- [x] Delete `teleclaude/core/command_handlers.py`

---

## Phase 3: Split db.py

### Task 3.1: Create db package skeleton

**File(s):** `teleclaude/core/db/`

- [x] Create `teleclaude/core/db/` directory
- [x] Create `teleclaude/core/db/_rows.py` — HookOutboxRow, InboundQueueRow, OperationRow TypedDicts
- [x] Create `teleclaude/core/db/_base.py` — DbBase class: imports, __init__, initialize, _normalize_adapter_metadata, _session, is_initialized, set_client, wal_checkpoint, close, static helpers
- [x] Create `teleclaude/core/db/_sessions.py` — DbSessionsMixin: all session CRUD methods
- [x] Create `teleclaude/core/db/_settings.py` — DbSettingsMixin: system settings, voice assignment, agent availability
- [x] Create `teleclaude/core/db/_hooks.py` — DbHooksMixin: hook outbox methods
- [x] Create `teleclaude/core/db/_inbound.py` — DbInboundMixin: inbound queue methods
- [x] Create `teleclaude/core/db/_operations.py` — DbOperationsMixin: operations methods
- [x] Create `teleclaude/core/db/_webhooks.py` — DbWebhooksMixin: webhook methods
- [x] Create `teleclaude/core/db/_listeners.py` — DbListenersMixin: session listener methods
- [x] Create `teleclaude/core/db/_links.py` — DbLinksMixin: conversation link methods
- [x] Create `teleclaude/core/db/_tokens.py` — DbTokensMixin: session token methods
- [x] Create `teleclaude/core/db/_sync.py` — module-level sync functions + resolve_session_principal
- [x] Create `teleclaude/core/db/__init__.py` — defines Db class (inherits mixins), creates singleton, re-exports all public names
- [x] Delete `teleclaude/core/db.py`

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Run `make test`

### Task 4.2: Quality Checks

- [x] Run `make lint` (ruff ✓, pyright ✓, mypy ✓ for all 3 packages; guardrail fails on 18 pre-existing violations outside scope — see deferrals.md)
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
