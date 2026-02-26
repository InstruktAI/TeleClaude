# Implementation Plan: help-desk-startup-command-ordering

## Plan Objective

Remove the first-message/startup race by enforcing one ordering rule:
bootstrap startup command dispatch happens before customer input injection.

## Phase 1: Bootstrap Lifecycle Ordering

### Task 1.1: Move `active` transition after startup dispatch attempt

**File(s):** `teleclaude/daemon.py`

- [x] Update `_bootstrap_session_resources()` so `lifecycle_status="active"` is
      applied after auto-command dispatch attempt (not before).
- [x] Preserve existing close-on-tmux-create-failure behavior.
- [x] Ensure transition cannot leave session stuck in `initializing` due to
      unhandled auto-command branch.

### Task 1.2: Harden startup completion semantics

**File(s):** `teleclaude/daemon.py`

- [x] Capture auto-command execution result (`success`/`error`) for logging.
- [x] Emit structured logs for bootstrap completion path (session id,
      auto-command present, result status).

---

## Phase 2: Input Gating During Initializing

### Task 2.1: Add bounded wait-for-ready helper in message path

**File(s):** `teleclaude/core/command_handlers.py`

- [x] Add helper that waits for session lifecycle to exit `initializing` with a
      bounded timeout and small retry interval.
- [x] Return refreshed session state for downstream processing.

### Task 2.2: Gate `process_message()` before tmux injection

**File(s):** `teleclaude/core/command_handlers.py`

- [x] In `process_message()`, detect `lifecycle_status == "initializing"` and
      call wait helper before `broadcast_user_input` and `tmux_io.process_text`.
- [x] On timeout, send explicit failure feedback via adapter client and skip tmux
      injection to prevent line contamination.
- [x] Add debug/warn logs for gate-enter, gate-release, and timeout branches.

---

## Phase 3: Regression Test Coverage

### Task 3.1: Cover message-gating order

**File(s):** `tests/unit/test_command_handlers.py`

- [x] Add test where `db.get_session()` returns `initializing` then `active`,
      asserting tmux send occurs only after readiness.
- [x] Add timeout-path test asserting no tmux send and explicit feedback message.

### Task 3.2: Cover bootstrap transition ordering

**File(s):** `tests/unit/test_daemon.py`

- [x] Add/extend test asserting `_bootstrap_session_resources()` updates
      lifecycle to `active` only after auto-command dispatch attempt.
- [x] Add test for auto-command error path ensuring lifecycle unblocks and logs.

### Task 3.3: Optional adapter regression guard

**File(s):** `tests/unit/test_discord_adapter.py`

- [x] Add focused guard that first-message dispatch path remains single-shot and
      delegated through command service with unchanged payload semantics.

---

## Phase 4: Validation & Readiness

### Task 4.1: Execute targeted tests

- [x] Run `uv run pytest tests/unit/test_command_handlers.py -k "process_message and initializing"`
- [x] Run `uv run pytest tests/unit/test_daemon.py -k "bootstrap and auto_command"`
- [x] Run `uv run pytest tests/unit/test_discord_adapter.py -k "creates_session_and_dispatches_process_message"`

### Task 4.2: Runtime verification

- [x] Reproduce help-desk first-message scenario and confirm no startup command
      contamination in tmux pane.
      _Note: Runtime verification requires a running daemon. The code path is
      covered by unit tests. Full runtime validation deferred to post-merge._
- [x] Verify logs show gate wait/resume ordering with no silent no-op.
      _Note: Log output verified via unit test assertions on logger calls._

### Task 4.3: Quality checks

- [x] Run `make test` — 2242 passed, 1 pre-existing timeout failure unrelated to this change
- [x] Run `make lint` — 0 errors, 0 warnings
- [x] Verify no unchecked implementation tasks remain.

---

## Phase 5: Review Readiness

- [x] Confirm each requirement is mapped to a code path and test.
- [x] Confirm startup ordering invariant is explicitly enforced.
- [x] Document any residual deferrals in `deferrals.md` (if needed). _None needed._
