# Implementation Plan: agent-availability-enforcement-migration

## Overview

Fix the availability bypass by centralizing runtime agent routing and migrating
all launch/restart surfaces to that one policy path. This plan is intentionally
cross-surface because the regression exists across API, daemon, adapters,
automation, and CLI scaffolding defaults.

## Phase 0: Policy Lock

### Task 0.1: Degraded-routing semantics — LOCKED (Option B)

**Decision:** Option B — block degraded agents for all selection (explicit + auto/default).
This matches the existing proven behavior in `helpers/agent_cli.py::_pick_agent`.

- [x] Degraded behavior locked to Option B (gate decision based on codebase precedent)
- [x] Codify Option B in the core resolver and tests during Phase 1

---

## Phase 1: Canonical Routing Helper

### Task 1.1: Introduce shared routable-agent resolver in core

**File(s):** `teleclaude/core/agent_routing.py` (new), `teleclaude/core/agents.py`, `teleclaude/core/db.py`

- [x] Add a core helper that resolves/validates routable agent names from:
      requested agent + source + selection mode
- [x] Enforce known/enabled/availability/degraded checks in one place
- [x] Reuse DB availability methods; do not duplicate inline SQL checks
- [x] Return stable errors for API and adapter consumption

### Task 1.2: Remove mapper-level enabled-only default selection

**File(s):** `teleclaude/core/command_mapper.py`, `teleclaude/types/commands.py`

- [x] Remove `_default_agent_name()` fallback behavior that picks first enabled agent
- [x] Ensure mapper payloads can carry "no explicit agent provided" and defer selection to runtime resolver
- [x] Preserve command mapping behavior for explicit agent commands

---

## Phase 2: Runtime Launch Enforcement

### Task 2.1: Migrate API launch endpoints to routable resolver

**File(s):** `teleclaude/api_server.py`, `teleclaude/api_models.py`

- [x] Replace enabled-only resolver logic in `/sessions` with canonical routable resolver
- [x] Replace enabled-only logic in `/sessions/run` with canonical routable resolver
- [x] Validate `auto_command` agent targets using canonical resolver
- [x] Remove hardcoded API model default that preselects `claude` for `/sessions/run`

### Task 2.2: Migrate command handlers and daemon auto-command path

**File(s):** `teleclaude/core/command_handlers.py`, `teleclaude/daemon.py`

- [x] Update `start_agent`, `resume_agent`, `agent_restart`, `run_agent_command`
      to enforce canonical routable policy
- [x] Update daemon `_execute_auto_command` / `_handle_agent_then_message`
      to enforce canonical routable policy before launch
- [x] Emit structured rejection logs with source context

---

## Phase 3: Adapter and Automation Migration

### Task 3.1: Migrate adapter launch defaults and hardcoded agent paths

**File(s):**

- `teleclaude/adapters/discord_adapter.py`
- `teleclaude/adapters/telegram_adapter.py`
- `teleclaude/adapters/telegram/callback_handlers.py`
- `teleclaude/hooks/whatsapp_handler.py`

- [x] Remove hardcoded runtime `agent claude` launch defaults
- [x] Ensure adapter-driven launch actions resolve through canonical routable policy
- [x] Preserve existing UX while failing closed on unavailable selections

### Task 3.2: Migrate cron and CLI bug scaffolding defaults

**File(s):** `teleclaude/cron/runner.py`, `teleclaude/cli/telec.py`, `teleclaude/cli/tool_commands.py`

- [x] Replace `config.agent or "claude"` runtime fallback in cron jobs with routed selection
- [x] Remove bug scaffold orchestrator hardcoded `agent="claude"` pin
- [x] Keep explicit `--agent` behavior while rejecting non-routable agents

---

## Phase 4: Verification and Observability

### Task 4.1: Add/adjust regression tests by surface

**File(s):**

- `tests/unit/test_api_server.py`
- `tests/unit/test_command_handlers.py`
- `tests/unit/test_command_mapper.py`
- `tests/unit/test_daemon.py`
- `tests/unit/test_discord_adapter.py`
- `tests/unit/test_telegram_adapter.py`
- `tests/unit/test_whatsapp_adapter.py`
- `tests/unit/test_cron_runner_job_contract.py`
- `tests/unit/cli/test_tool_commands.py`

- [x] Explicit unavailable agent selection is rejected
- [x] Implicit/default selection never routes to unavailable agent
- [x] Degraded behavior matches the locked policy decision
- [x] Hardcoded-default paths are removed or routed through policy

### Task 4.2: Runtime checks

- [x] Run targeted test set for migrated surfaces
- [x] Run `make test`
- [x] Run `make lint`
- [x] Validate rejection logs via:
      `instrukt-ai-logs teleclaude --since 15m --grep "agent routing|availability|rejected"`

## Requirement Traceability

- Task 0.1 -> FR2
- Task 1.1 -> FR1, FR2
- Task 1.2 -> FR1, FR4
- Task 2.1 -> FR1, FR3
- Task 2.2 -> FR1, FR4, FR6
- Task 3.1 -> FR5, FR6
- Task 3.2 -> FR5, FR7
- Task 4.1 / 4.2 -> Success criteria verification for FR1-FR7
