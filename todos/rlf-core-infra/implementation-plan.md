# Implementation Plan: rlf-core-infra

## Overview

Structural decomposition of three core infrastructure files into packages.
Each file is converted to a package directory with an `__init__.py` that re-exports
the original public API for backward compatibility. No behavior changes.

Constraints:
- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies.
- No test changes.
- `make lint` and type checking must pass.
- Commit atomically per file.

---

## Phase 1: tmux_bridge.py (1,402 lines → package)

**Split into:**
- `tmux_bridge/_subprocess.py` — timeout constants, `SubprocessTimeoutError`, `wait_with_timeout`, `communicate_with_timeout`
- `tmux_bridge/_session.py` — `_SHELL_NAME`, path helpers, session creation/guardrails, `ensure_tmux_session`, `update_tmux_session`
- `tmux_bridge/_keys.py` — key sending functions (`send_keys`, `_send_keys_tmux`, signals, special keys)
- `tmux_bridge/_pane.py` — pane operations (`capture_pane`, `session_exists`, `is_pane_dead`, pipe, query functions)
- `tmux_bridge/__init__.py` — re-exports all public API from submodules

**Dependency order within package:**
- `_subprocess.py` → no internal deps
- `_pane.py` → `_subprocess.py`
- `_session.py` → `_subprocess.py`, `_pane.py` (for `session_exists`)
- `_keys.py` → `_subprocess.py`, `_session.py`

### Task 1.1: Create tmux_bridge package submodules

**File(s):** `teleclaude/core/tmux_bridge/_subprocess.py`, `_session.py`, `_keys.py`, `_pane.py`

- [x] Create `_subprocess.py` with timeout constants, error class, and async helpers
- [x] Create `_pane.py` with pane/session query functions
- [x] Create `_session.py` with session creation and shell guardrail functions
- [x] Create `_keys.py` with key-sending functions

### Task 1.2: Convert tmux_bridge.py to package __init__.py

**File(s):** `teleclaude/core/tmux_bridge/__init__.py` (via git mv of original)

- [x] `git mv` original to `__init__.py`
- [x] Replace `__init__.py` content with re-exports only

---

## Phase 2: agent_coordinator.py (1,628 lines → package)

**Split into:**
- `agent_coordinator/_helpers.py` — standalone functions: `_SuppressionState`, checkpoint detectors, output/identity resolvers, timestamp utils, constants
- `agent_coordinator/_incremental.py` — `_IncrementalOutputMixin`: suppression + incremental output methods
- `agent_coordinator/_fanout.py` — `_FanoutMixin`: extraction, fanout, forwarding, notify, TTS, snapshot, checkpoint injection
- `agent_coordinator/_coordinator.py` — core `AgentCoordinator` class inheriting mixins, all `handle_*` methods, event emission, stall detection
- `agent_coordinator/__init__.py` — re-exports `AgentCoordinator`, `SESSION_START_MESSAGES`

### Task 2.1: Create agent_coordinator package submodules

**File(s):** `teleclaude/core/agent_coordinator/_helpers.py`, `_incremental.py`, `_fanout.py`

- [x] Create `_helpers.py` with standalone functions
- [x] Create `_incremental.py` with `_IncrementalOutputMixin` (suppression + incremental output)
- [x] Create `_fanout.py` with `_FanoutMixin` (extraction, fanout, forwarding, TTS, snapshot, checkpoint)

### Task 2.2: Convert agent_coordinator.py to package __init__.py

**File(s):** `teleclaude/core/agent_coordinator/_coordinator.py`, `__init__.py`

- [x] Create `_coordinator.py` with core `AgentCoordinator` class
- [x] `git mv` original to `__init__.py`
- [x] Replace `__init__.py` content with re-exports only

---

## Phase 3: adapter_client.py (1,161 lines → package)

**Split into:**
- `adapter_client/_channels.py` — `_ChannelsMixin`: `create_channel`, `ensure_ui_channels`, `update_channel_title`, `delete_channel`, `get_output_message_id`
- `adapter_client/_remote.py` — `_RemoteMixin`: peer discovery, remote request/response, action broadcasting, command handlers
- `adapter_client/_client.py` — core `AdapterClient(_ChannelsMixin, _RemoteMixin)`: lifecycle, routing, messaging
- `adapter_client/__init__.py` — re-exports `AdapterClient`

### Task 3.1: Create adapter_client package submodules

**File(s):** `teleclaude/core/adapter_client/_channels.py`, `_remote.py`

- [x] Create `_channels.py` with `_ChannelsMixin`
- [x] Create `_remote.py` with `_RemoteMixin`

### Task 3.2: Convert adapter_client.py to package __init__.py

**File(s):** `teleclaude/core/adapter_client/_client.py`, `__init__.py`

- [x] Create `_client.py` with core `AdapterClient` class
- [x] `git mv` original to `__init__.py`
- [x] Replace `__init__.py` content with re-exports only

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Run `make test`

### Task 4.2: Quality Checks

- [x] Run `make lint` — ruff PASS, pyright PASS (0 errors); mypy deferred (pre-existing baseline 5844 errors, documented in deferrals.md)
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
