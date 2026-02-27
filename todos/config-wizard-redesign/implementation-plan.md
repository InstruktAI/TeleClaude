# Implementation Plan: config-wizard-redesign

## Overview

This todo upgrades the Textual config wizard from passive status rendering to an interactive setup flow. The plan is intentionally Textual-first, keeps legacy curses as fallback, and routes env persistence through shared config handlers.

## Phase 1: Data and persistence foundations

### Task 1.1: Add env mutation helper in shared config layer

**File(s):** `teleclaude/cli/config_handlers.py`, `tests/unit/test_config_handlers.py`

- [x] Add helper(s) to resolve target env file path for writes (honor `TELECLAUDE_ENV_PATH` when set, otherwise default project `.env` path)
- [x] Add `set_env_var(...)` style API in `config_handlers.py` for update-or-append behavior
- [x] Ensure helper updates both file content and `os.environ` for immediate runtime visibility
- [x] Add unit tests for create/update behavior and env-path override behavior

### Task 1.2: Add config view status/progress projection helpers

**File(s):** `teleclaude/cli/tui/views/config.py`, `tests/unit/test_tui_config_view.py`

- [x] Add helper logic to project adapter status (`configured|partial|unconfigured`) from env var state
- [x] Add helper logic for overall completion summary used by the view header/progress area
- [x] Add unit tests for status classification and progress calculations

---

## Phase 2: Textual UX redesign

### Task 2.1: Replace flat text rendering with structured Textual layout

**File(s):** `teleclaude/cli/tui/views/config.py`, `teleclaude/cli/tui/telec.tcss`

- [x] Replace flat list output with sectioned/card-like layout using Textual widgets
- [x] Render adapter section status badges and grouped env var rows
- [x] Keep existing key bindings (`tab`, `shift+tab`, arrow navigation, `v`, `r`) functional
- [x] Add CSS rules to support hierarchy/spacing/selection states for the redesigned config surface

### Task 2.2: Implement inline editing flow for env vars

**File(s):** `teleclaude/cli/tui/views/config.py`, `teleclaude/cli/config_handlers.py`, `tests/unit/test_tui_config_view.py`

- [x] Enter on a selectable env var transitions to inline input mode
- [x] Save path calls the shared env mutation helper and refreshes config state
- [x] Cancel path exits edit mode without mutating file/env
- [x] Errors surface as explicit UI feedback; successful save refreshes status/progress
- [x] Add tests for save/cancel/error edit flows

### Task 2.3: Implement guided onboarding progression

**File(s):** `teleclaude/cli/tui/views/config.py`, `tests/unit/test_tui_config_view.py`

- [x] Define deterministic guided sequence across adapters/core sections
- [x] Show step counter and completion progress in guided mode
- [x] Ensure guided progression reacts to post-edit validation state
- [x] Add tests for step transitions and completion conditions

### Task 2.4: Replace notifications placeholder with actionable surface

**File(s):** `teleclaude/cli/tui/views/config.py`, `tests/unit/test_tui_config_view.py`

> Note: The Textual notifications rendering is inline in `config.py:_render_notifications`, not in the curses component `config_components/notifications.py`. Focus Textual work here.

- [x] Remove literal placeholder copy `(Not implemented yet)` from `_render_notifications`
- [x] Show current notification configuration summary and explicit next action command/path
- [x] Add regression test to ensure placeholder text does not return

---

## Phase 3: Legacy fallback guardrail

### Task 3.1: Keep curses view functional as fallback with explicit legacy framing

**File(s):** `teleclaude/cli/tui/views/configuration.py`

- [x] Keep existing behavior stable (no parity rewrite required)
- [x] Add clear copy that interactive editing is in the Textual config view

---

## Phase 4: Validation and review readiness

### Task 4.1: Automated checks

- [x] Run targeted tests: `python -m pytest tests/unit/test_config_handlers.py tests/unit/test_tui_config_view.py`
- [x] Run full checks: `make test`
- [x] Run lint: `make lint`

### Task 4.2: TUI verification

- [x] Reload running TUI after code changes: `pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"`
- [x] Verify redesigned config UX manually in the TUI (navigation, edit, save, guided progression, validation)

### Task 4.3: Review readiness

- [x] Confirm each success criterion in `requirements.md` is mapped to implemented behavior and tests
- [x] Confirm all implementation-plan checkboxes are `[x]`
- [x] Document any explicit deferrals in `deferrals.md` if scope is intentionally cut
