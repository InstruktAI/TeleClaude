# Implementation Plan: agent-dispatch-guidance

## Overview

Replace hardcoded agent selection matrices (`WORK_FALLBACK`, `PREPARE_FALLBACK`, `get_available_agent()`, `_pick_agent()`) with config-driven guidance text. The next-machine stops picking agents deterministically — instead it composes a guidance block from `config.yml` agent entries and embeds it in dispatch instructions. The orchestrator AI reads the work item and the guidance, then selects agent + thinking mode.

This approach is appropriate because domain inference (frontend vs backend vs oversight) is an AI-native task, not something that benefits from hardcoded matrices. Config-driven availability is simpler, more maintainable, and lets the user declare agent strengths per machine.

## Phase 1: Config Schema & Loading

### Task 1.1: Add AgentDispatchConfig to config schema

**File(s):** `teleclaude/config/schema.py`

- [x] Add `AgentDispatchConfig` Pydantic model with `enabled: bool = True`, `strengths: str = ""`, `avoid: str = ""`
- [x] Write tests in `tests/unit/test_agent_dispatch_config.py`

### Task 1.2: Add `enabled`/`strengths`/`avoid` to AgentConfig and wire config.yml loading

**File(s):** `teleclaude/config/__init__.py`

- [x] Add `enabled`, `strengths`, `avoid` fields to `AgentConfig` dataclass
- [x] Remove `agents` from `_validate_disallowed_runtime_keys`
- [x] Overlay config.yml agents section in `_build_config`
- [x] Write tests

### Task 1.3: Add agents section to config.yml

**File(s):** `config.yml`, `tests/integration/config.yml`

- [x] Add `agents:` section with claude/gemini/codex entries
- [x] Verify existing tests pass (backwards compatible)

---

## Phase 2: Core Logic

### Task 2.1: Write compose_agent_guidance function

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Implement `compose_agent_guidance(agents, db)` that builds guidance text from enabled agents + DB availability
- [x] Handle disabled agents (excluded), degraded agents (noted with status), no agents (error)
- [x] Include thinking mode guidance (slow/med/fast heuristics)
- [x] Write tests in `tests/unit/test_agent_guidance.py`

### Task 2.2: Modify format_tool_call to use guidance

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Replace `agent` and `thinking_mode` params with `guidance: str`
- [x] Use placeholders `agent="<your selection>"`, `thinking_mode="<your selection>"`
- [x] Embed guidance block in STEP 1
- [x] Write tests

### Task 2.3: Update all call sites — delete matrices and wire guidance

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Delete `PREPARE_FALLBACK`, `WORK_FALLBACK`, `NO_SELECTABLE_AGENTS_PATTERN`
- [x] Delete `get_available_agent()`, `_extract_no_selectable_task_type()`, `format_agent_selection_error()`
- [x] Delete inner `_pick_agent()` in `next_work()`
- [x] Replace all call sites in `next_work()` (5 sites) and `next_prepare()` (6 sites) with `compose_agent_guidance` + updated `format_tool_call`
- [x] Wire config access: `from teleclaude.config import config as app_config` (same pattern as `teleclaude/mcp/handlers.py:24`), build agents dict from `app_config.agents`

---

## Phase 3: Test Migration

### Task 3.1: Update tests that mock old agent selection

**File(s):** `tests/unit/test_next_machine_breakdown.py`, `tests/unit/test_next_machine_state_deps.py`, `tests/unit/core/test_next_machine_deferral.py`

- [x] Remove `test_get_available_agent_skips_degraded` (behavior now tested via compose_agent_guidance tests)
- [x] Update mocks from `get_available_agent` → `compose_agent_guidance`
- [x] All existing tests pass

---

## Phase 4: Cleanup & Docs

### Task 4.1: Update agent_cli.\_pick_agent

**File(s):** `teleclaude/helpers/agent_cli.py`

- [x] Respect `config.agents[name].enabled` in standalone agent picker
- [x] Tests pass

### Task 4.2: Update doc snippets

**File(s):** `docs/project/spec/teleclaude-config.md`, `docs/project/design/architecture/next-machine.md`

- [x] Document agents config section
- [x] Update next-machine design for guidance-based dispatch

---

## Phase 5: Validation

### Task 5.1: Tests

- [x] All new unit tests pass
- [x] All migrated tests pass
- [x] Run `make test`

### Task 5.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
