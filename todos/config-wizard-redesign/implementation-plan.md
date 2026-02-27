# Implementation Plan: config-wizard-redesign

## Overview

This todo upgrades the Textual config wizard from passive status rendering to an interactive setup flow. The plan is intentionally Textual-first, keeps legacy curses as fallback, and routes env persistence through shared config handlers.

## Phase 1: Data and persistence foundations

### Task 1.1: Add env mutation helper in shared config layer

**File(s):** `teleclaude/cli/config_handlers.py`, `tests/unit/test_config_handlers.py`

- [ ] Add helper(s) to resolve target env file path for writes (honor `TELECLAUDE_ENV_PATH` when set, otherwise default project `.env` path)
- [ ] Add `set_env_var(...)` style API in `config_handlers.py` for update-or-append behavior
- [ ] Ensure helper updates both file content and `os.environ` for immediate runtime visibility
- [ ] Add unit tests for create/update behavior and env-path override behavior

### Task 1.2: Add config view status/progress projection helpers

**File(s):** `teleclaude/cli/tui/views/config.py`, `tests/unit/test_tui_config_view.py`

- [ ] Add helper logic to project adapter status (`configured|partial|unconfigured`) from env var state
- [ ] Add helper logic for overall completion summary used by the view header/progress area
- [ ] Add unit tests for status classification and progress calculations

---

## Phase 2: Textual UX redesign

### Task 2.1: Replace flat text rendering with structured Textual layout

**File(s):** `teleclaude/cli/tui/views/config.py`, `teleclaude/cli/tui/telec.tcss`

- [ ] Replace flat list output with sectioned/card-like layout using Textual widgets
- [ ] Render adapter section status badges and grouped env var rows
- [ ] Keep existing key bindings (`tab`, `shift+tab`, arrow navigation, `v`, `r`) functional
- [ ] Add CSS rules to support hierarchy/spacing/selection states for the redesigned config surface

### Task 2.2: Implement inline editing flow for env vars

**File(s):** `teleclaude/cli/tui/views/config.py`, `teleclaude/cli/config_handlers.py`, `tests/unit/test_tui_config_view.py`

- [ ] Enter on a selectable env var transitions to inline input mode
- [ ] Save path calls the shared env mutation helper and refreshes config state
- [ ] Cancel path exits edit mode without mutating file/env
- [ ] Errors surface as explicit UI feedback; successful save refreshes status/progress
- [ ] Add tests for save/cancel/error edit flows

### Task 2.3: Implement guided onboarding progression

**File(s):** `teleclaude/cli/tui/views/config.py`, `tests/unit/test_tui_config_view.py`

- [ ] Define deterministic guided sequence across adapters/core sections
- [ ] Show step counter and completion progress in guided mode
- [ ] Ensure guided progression reacts to post-edit validation state
- [ ] Add tests for step transitions and completion conditions

### Task 2.4: Replace notifications placeholder with actionable surface

**File(s):** `teleclaude/cli/tui/views/config.py`, `tests/unit/test_tui_config_view.py`

> Note: The Textual notifications rendering is inline in `config.py:_render_notifications`, not in the curses component `config_components/notifications.py`. Focus Textual work here.

- [ ] Remove literal placeholder copy `(Not implemented yet)` from `_render_notifications`
- [ ] Show current notification configuration summary and explicit next action command/path
- [ ] Add regression test to ensure placeholder text does not return

---

## Phase 3: Legacy fallback guardrail

### Task 3.1: Keep curses view functional as fallback with explicit legacy framing

**File(s):** `teleclaude/cli/tui/views/configuration.py`

- [ ] Keep existing behavior stable (no parity rewrite required)
- [ ] Add clear copy that interactive editing is in the Textual config view

---

## Phase 4: Validation and review readiness

### Task 4.1: Automated checks

- [ ] Run targeted tests: `python -m pytest tests/unit/test_config_handlers.py tests/unit/test_tui_config_view.py`
- [ ] Run full checks: `make test`
- [ ] Run lint: `make lint`

### Task 4.2: TUI verification

- [ ] Reload running TUI after code changes: `pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"`
- [ ] Verify redesigned config UX manually in the TUI (navigation, edit, save, guided progression, validation)

### Task 4.3: Review readiness

- [ ] Confirm each success criterion in `requirements.md` is mapped to implemented behavior and tests
- [ ] Confirm all implementation-plan checkboxes are `[x]`
- [ ] Document any explicit deferrals in `deferrals.md` if scope is intentionally cut
