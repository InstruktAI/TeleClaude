# Implementation Plan: help-desk-startup-command-ordering

## Plan Objective

Remove the first-message/startup race by enforcing one ordering rule:
bootstrap startup command dispatch happens before customer input injection.

## Phase 1: Bootstrap Lifecycle Ordering

### Task 1.1: Move `active` transition after startup dispatch attempt

**File(s):** `teleclaude/daemon.py`

- [ ] Update `_bootstrap_session_resources()` so `lifecycle_status="active"` is
      applied after auto-command dispatch attempt (not before).
- [ ] Preserve existing close-on-tmux-create-failure behavior.
- [ ] Ensure transition cannot leave session stuck in `initializing` due to
      unhandled auto-command branch.

### Task 1.2: Harden startup completion semantics

**File(s):** `teleclaude/daemon.py`

- [ ] Capture auto-command execution result (`success`/`error`) for logging.
- [ ] Emit structured logs for bootstrap completion path (session id,
      auto-command present, result status).

---

## Phase 2: Input Gating During Initializing

### Task 2.1: Add bounded wait-for-ready helper in message path

**File(s):** `teleclaude/core/command_handlers.py`

- [ ] Add helper that waits for session lifecycle to exit `initializing` with a
      bounded timeout and small retry interval.
- [ ] Return refreshed session state for downstream processing.

### Task 2.2: Gate `process_message()` before tmux injection

**File(s):** `teleclaude/core/command_handlers.py`

- [ ] In `process_message()`, detect `lifecycle_status == "initializing"` and
      call wait helper before `broadcast_user_input` and `tmux_io.process_text`.
- [ ] On timeout, send explicit failure feedback via adapter client and skip tmux
      injection to prevent line contamination.
- [ ] Add debug/warn logs for gate-enter, gate-release, and timeout branches.

---

## Phase 3: Regression Test Coverage

### Task 3.1: Cover message-gating order

**File(s):** `tests/unit/test_command_handlers.py`

- [ ] Add test where `db.get_session()` returns `initializing` then `active`,
      asserting tmux send occurs only after readiness.
- [ ] Add timeout-path test asserting no tmux send and explicit feedback message.

### Task 3.2: Cover bootstrap transition ordering

**File(s):** `tests/unit/test_daemon.py`

- [ ] Add/extend test asserting `_bootstrap_session_resources()` updates
      lifecycle to `active` only after auto-command dispatch attempt.
- [ ] Add test for auto-command error path ensuring lifecycle unblocks and logs.

### Task 3.3: Optional adapter regression guard

**File(s):** `tests/unit/test_discord_adapter.py`

- [ ] Add focused guard that first-message dispatch path remains single-shot and
      delegated through command service with unchanged payload semantics.

---

## Phase 4: Validation & Readiness

### Task 4.1: Execute targeted tests

- [ ] Run `uv run pytest tests/unit/test_command_handlers.py -k "process_message and initializing"`
- [ ] Run `uv run pytest tests/unit/test_daemon.py -k "bootstrap and auto_command"`
- [ ] Run `uv run pytest tests/unit/test_discord_adapter.py -k "creates_session_and_dispatches_process_message"`

### Task 4.2: Runtime verification

- [ ] Reproduce help-desk first-message scenario and confirm no startup command
      contamination in tmux pane.
- [ ] Verify logs show gate wait/resume ordering with no silent no-op.

### Task 4.3: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 5: Review Readiness

- [ ] Confirm each requirement is mapped to a code path and test.
- [ ] Confirm startup ordering invariant is explicitly enforced.
- [ ] Document any residual deferrals in `deferrals.md` (if needed).
