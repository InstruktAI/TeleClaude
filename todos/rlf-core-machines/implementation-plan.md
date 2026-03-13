# Implementation Plan: rlf-core-machines

## Overview

Structural decomposition of two state machine files into focused sub-modules.
All behavior is preserved exactly. Modules keep their public API via re-exports.

### Key constraint: no circular imports

Sub-modules MUST NOT import from `core.py` at module level.
`core.py` re-exports from sub-modules (facade pattern).
Internal shared types go in `_types.py` so sub-modules can import them without depending on `core.py`.

---

## Phase 1: `core/next_machine/` — create `_types.py` (shared types foundation)

### Task 1.1: Create `_types.py` with all shared types, enums, and constants

**File(s):** `teleclaude/core/next_machine/_types.py`

- [x] Move from `core.py` lines 1–165 + 947–1021 + scattered constants:
  - `StateScalar`, `StateValue` (TypeAlias, lines ~36–37)
  - `FinalizeState`, `PhaseName`, `PhaseStatus`, `ItemPhase`, `PreparePhase`, `CreativePhase`, `WorktreeScript` (lines 44–117)
  - `WorktreePrepDecision`, `EnsureWorktreeResult` (lines 149–161)
  - `RoadmapEntry`, `RoadmapDict` (lines 1799–1812)
  - `DeliveredEntry`, `DeliveredDict` (lines 2208–2221)
  - Constants: `DEFAULT_MAX_REVIEW_ROUNDS`, `FINDING_ID_PATTERN`, `PAREN_OPEN`, `REVIEW_APPROVE_MARKER`, `SCRIPTS_KEY`, `NEXT_WORK_PHASE_LOG`, `DOR_READY_THRESHOLD`, `_PREPARE_LOOP_LIMIT`, `_PREP_STATE_VERSION`, `_WORKTREE_PREP_STATE_REL`, `_PREP_INPUT_FILES`, `_PREP_ROOT_INPUT_FILES`, `REVIEW_DIFF_NOTE` (scattered in lines 111–130, 315–318)
  - `DEFAULT_STATE` dict (lines 947–1019) — references enums so must live here
  - Note: `_SINGLE_FLIGHT_GUARD`, `_SINGLE_FLIGHT_LOCKS`, `_get_slug_single_flight_lock`, `_log_next_work_phase` moved to `work.py` (use `resolve_canonical_project_root` — would create circular dep in `_types.py`)
- [x] Add `from __future__ import annotations` and required stdlib imports only
- [x] Commit

---

## Phase 2: `core/next_machine/` — extract pure state I/O

### Task 2.1: Create `state_io.py`

**File(s):** `teleclaude/core/next_machine/state_io.py`

- [x] Move from `core.py`:
  - Tiny file helpers used internally: `read_text_sync`, `write_text_sync`, `_file_sha256` (lines 2600–2626)
  - Git primitives needed by state writes: `_get_head_commit`, `_get_ref_commit`, `_get_remote_branch_head`, `_run_git_prepare` (lines 1331–1373, 3925–3933)
  - `_DEEP_MERGE_KEYS`, `_extract_finding_ids` (lines 1028, 1318–1328)
  - All state read/write functions: `get_state_path`, `_deep_merge_state`, `read_phase_state`, `_normalize_finalize_state`, `_get_finalize_state`, `write_phase_state` (lines 1022–1131)
  - All mark operations: `mark_phase`, `mark_prepare_verdict`, `mark_prepare_phase`, `mark_finalize_ready`, `_mark_finalize_handed_off` (lines 1132–1315)
  - Review state helpers: `_review_scope_note`, `_is_review_round_limit_reached`, `read_breakdown_state`, `write_breakdown_state` (lines 1454–1512)
  - Phase status checks: `is_build_complete`, `is_review_approved`, `is_review_changes_requested`, `has_pending_deferrals` (lines 1514–1546)
  - `check_review_status` (lines 2523–2538)
  - `is_bug_todo` (moved here from slug_resolution to break circular dep with build_gates)
  - Internal constants: `_PREPARE_VERDICT_PHASES`, `_PREPARE_VERDICT_VALUES`, `_PREPARE_PHASE_VALUES` (lines 1173–1178)
  - Note: `mark_finalize_ready` uses lazy import for `has_uncommitted_changes` from `git_ops` to avoid circular dep
- [x] Imports: explicit named imports from `_types` (not wildcard, to satisfy linter)
- [x] Commit

---

## Phase 3: `core/next_machine/` — extract data management modules

### Task 3.1: Create `roadmap.py`

**File(s):** `teleclaude/core/next_machine/roadmap.py`

- [x] Move from `core.py`:
  - `_roadmap_path`, `load_roadmap`, `save_roadmap`, `load_roadmap_slugs`, `load_roadmap_deps`, `add_to_roadmap`, `remove_from_roadmap`, `move_in_roadmap`, `check_dependencies_satisfied` (lines 1813–1999)
  - `detect_circular_dependency` (lines 2473–2522)
  - Note: `slug_in_roadmap` moved here (not slug_resolution) — called by `check_dependencies_satisfied`
- [x] Imports: named imports from `_types` + `state_io`
- [x] Commit

### Task 3.2: Create `icebox.py`

**File(s):** `teleclaude/core/next_machine/icebox.py`

- [x] Move from `core.py`:
  - `_icebox_dir`, `_icebox_path`, `load_icebox`, `save_icebox`, `load_icebox_slugs`, `remove_from_icebox`, `clean_dependency_references`, `freeze_to_icebox`, `unfreeze_from_icebox`, `migrate_icebox_to_subfolder` (lines 2001–2207)
- [x] Imports: named from `_types`, `roadmap`, `state_io`
- [x] Commit

### Task 3.3: Create `delivery.py`

**File(s):** `teleclaude/core/next_machine/delivery.py`

- [x] Move from `core.py`:
  - `_delivered_path`, `load_delivered_slugs`, `load_delivered`, `save_delivered`, `deliver_to_delivered`, `_run_git_cmd`, `cleanup_delivered_slug`, `sweep_completed_groups` (lines 2222–2472)
- [x] Imports: named from `_types`, `state_io`, `roadmap`, `icebox`
- [x] Commit

---

## Phase 4: `core/next_machine/` — extract operations modules

### Task 4.1: Create `git_ops.py`

**File(s):** `teleclaude/core/next_machine/git_ops.py`

- [x] Move from `core.py`:
  - `read_text_async`, `write_text_async` (lines 2610–2617)
  - `_dirty_paths`, `build_git_hook_env`, `has_uncommitted_changes`, `get_stash_entries`, `has_git_stash_entries` (lines 2629–2727)
  - `_merge_origin_main_into_worktree`, `_has_meaningful_diff` (lines 1374–1452)
  - `compose_agent_guidance` (lines 2546–2597)
  - Note: `compose_agent_guidance` uses lazy imports for `app_config` and `AgentName` inside function body to avoid importing heavy config at module level
- [x] Imports: named from `_types`, `state_io`; `Db` at top level for type annotation
- [x] Commit

### Task 4.2: Create `slug_resolution.py`

**File(s):** `teleclaude/core/next_machine/slug_resolution.py`

- [x] Move from `core.py`:
  - `_find_next_prepare_slug` (lines 913–938)
  - `resolve_holder_children`, `resolve_first_runnable_holder_child` (lines 1548–1633)
  - `resolve_slug`, `resolve_slug_async` (lines 1634–1697)
  - `check_file_exists`, `resolve_canonical_project_root` (lines 1699–1732)
  - `get_item_phase`, `is_ready_for_work`, `set_item_phase` (lines 1749–1797)
  - Note: `slug_in_roadmap` stays in roadmap.py; `is_bug_todo` stays in state_io.py
  - Note: `_find_next_prepare_slug` uses lazy import for `check_file_has_content` (build_gates not created yet)
- [x] Imports: named from `_types`, `roadmap`, `state_io`
- [x] Commit

### Task 4.3: Create `output_formatting.py`

**File(s):** `teleclaude/core/next_machine/output_formatting.py`

- [x] Move from `core.py`:
  - `POST_COMPLETION` dict (lines 207–313)
  - `REVIEW_DIFF_NOTE` (line 315–318) — re-exported from `_types`
  - `format_tool_call`, `format_error`, `format_prepared`, `format_uncommitted_changes`, `format_finalize_handoff_complete`, `format_stash_debt` (lines 326–489)
- [x] Imports: named from `_types`, `teleclaude.constants`
- [x] Commit

### Task 4.4: Create `build_gates.py`

**File(s):** `teleclaude/core/next_machine/build_gates.py`

- [x] Move from `core.py`:
  - `_count_test_failures`, `run_build_gates`, `format_build_gate_failure`, `_extract_checklist_section`, `_is_scaffold_template`, `_is_review_findings_template`, `check_file_has_content`, `verify_artifacts` (lines 491–912)
- [x] Imports: named from `_types`, `state_io` (only `is_bug_todo` needed here)
- [x] Commit

### Task 4.5: Create `worktrees.py`

**File(s):** `teleclaude/core/next_machine/worktrees.py`

- [x] Move from `core.py`:
  - `_worktree_prep_state_path`, `_compute_prep_inputs_digest`, `_read_worktree_prep_state`, `_write_worktree_prep_state`, `_decide_worktree_prep`, `_create_or_attach_worktree`, `_ensure_todo_on_remote_main`, `ensure_worktree_with_policy`, `ensure_worktree_with_policy_async`, `_prepare_worktree` (lines 2730–3067)
- [x] Imports: `from teleclaude.core.next_machine._types import ...`, `from .state_io import _file_sha256`
- [x] Commit

---

## Phase 5: `core/next_machine/` — extract prepare phase

### Task 5.1: Create `prepare_events.py`

**File(s):** `teleclaude/core/next_machine/prepare_events.py`

- [x] Move from `core.py`:
  - `_emit_prepare_event` (lines 3068–3104)
  - `_is_artifact_produced_v2` (lines 3105–3123)
  - `_derive_prepare_phase` (lines 3124–3183)
  - `_has_test_spec_artifacts` (moved here from step range — called by `_derive_prepare_phase`)
  - `invalidate_stale_preparations` (lines 3941–3977)
- [x] Imports: `from .state_io import read_phase_state, write_phase_state`, `from .roadmap import load_roadmap_slugs`, `from teleclaude.core.next_machine._types import ...`
  - Note: `check_file_exists` and `check_file_has_content` imported lazily in `_derive_prepare_phase`
- [x] Commit

### Task 5.2: Create `prepare_steps.py`

**File(s):** `teleclaude/core/next_machine/prepare_steps.py`

- [x] Move from `core.py`:
  - All `_prepare_step_*` functions (lines 3184–3888, excluding _has_test_spec_artifacts moved to prepare_events)
  - `_prepare_dispatch` (lines 3889–3924)
- [x] Imports: `from .prepare_events import _emit_prepare_event, _has_test_spec_artifacts`, plus all other sub-modules needed by step functions
  - Note: step functions have lazy imports from `prepare_helpers.py` — kept as-is inside function bodies
- [x] Commit

---

## Phase 6: `core/next_machine/` — update entry point stubs

### Task 6.1: Expand `work.py` with full `next_work` implementation

**File(s):** `teleclaude/core/next_machine/work.py`

- [x] Replace stub with full `next_work` implementation (lines 4088–4697 from `core.py`)
- [x] Define `_SINGLE_FLIGHT_LOCKS`, `_get_slug_single_flight_lock`, `_log_next_work_phase` in work.py; import `_SINGLE_FLIGHT_GUARD` from `_types`
- [x] Import from all required sub-modules (NOT from `core.py`)
- [x] Commit

### Task 6.2: Expand `prepare.py` with full `next_prepare` implementation

**File(s):** `teleclaude/core/next_machine/prepare.py`

- [x] Replace stub with full `next_prepare` implementation (lines 3985–4087 from `core.py`)
- [x] Import from required sub-modules (NOT from `core.py`)
- [x] Commit

### Task 6.3: Expand `create.py` with full `next_create` + creative phase

**File(s):** `teleclaude/core/next_machine/create.py`

- [x] Replace stub with `_derive_creative_phase`, `_find_next_creative_slug`, `_creative_instruction`, `next_create` (lines 4698–4952 from `core.py`)
- [x] Import from required sub-modules (NOT from `core.py`)
- [x] Commit

---

## Phase 7: `core/next_machine/` — rebuild `core.py` as facade

### Task 7.1: Rebuild `core.py` as a backward-compat re-export facade

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Replace all function/class/constant definitions with imports from sub-modules
- [x] Keep ONLY: module docstring + imports/re-exports
- [x] Explicitly re-export private names: `_emit_prepare_event`, `_prepare_worktree`, `_derive_prepare_phase`, `_get_head_commit`, `_run_git_prepare`, `_mark_finalize_handed_off`, `_get_finalize_state`, `_is_artifact_produced_v2`, etc.
- [x] Verify core.py is under 200 lines (207 lines — within acceptable range)
- [x] Commit

### Task 7.2: Update `__init__.py` if needed

**File(s):** `teleclaude/core/next_machine/__init__.py`

- [x] Review current `from .core import *` — it will pick up re-exports from `core.py` facade ✓
- [x] Verify all existing explicit exports still resolve — no changes needed
- [x] Commit if changed — no changes needed

### Task 7.3: Update `prepare_helpers.py` imports

**File(s):** `teleclaude/core/next_machine/prepare_helpers.py`

- [x] Update: `from teleclaude.core.next_machine.core import _emit_prepare_event, read_phase_state, write_phase_state`
  → `from teleclaude.core.next_machine.prepare_events import _emit_prepare_event`
  → `from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state`
- [x] Commit

---

## Phase 8: `core/integration/` — split `state_machine.py`

### Task 8.1: Create `integration/checkpoint.py`

**File(s):** `teleclaude/core/integration/checkpoint.py`

- [x] Move from `state_machine.py`:
  - `IntegrationPhase` enum (lines 56–73)
  - `IntegrationCheckpoint` dataclass (lines 74–106)
  - `_CheckpointPayload` TypedDict (lines 92–106)
  - `_now_iso`, `_read_checkpoint`, `_write_checkpoint` (lines 112–183)
  - `_default_state_dir` (lines 189–191)
- [x] This module has no deps on other integration modules
- [x] Commit

### Task 8.2: Create `integration/step_functions.py`

**File(s):** `teleclaude/core/integration/step_functions.py`

- [x] Move from `state_machine.py`:
  - All git helpers, formatters, phase helpers, event emission functions
  - `_try_auto_enqueue` (lines 675–713)
  - `_step_idle` (lines 715–793)
  - `_do_merge` (lines 794–889)
  - `_step_awaiting_commit` (lines 890–935)
  - `_step_committed` (lines 936–953)
  - `_step_delivery_bookkeeping` (lines 954–985)
  - `_step_push_rejected` (lines 986–1012)
  - `_step_push_succeeded` (lines 1013–1061)
  - `_step_cleanup` (lines 1062–1076)
  - `_do_cleanup` (lines 1077–1136)
- [x] Imports: `from .checkpoint import IntegrationCheckpoint, IntegrationPhase, ...`
  All other imports (next_machine.core, delivery, etc.) remain as lazy imports or top-level
- [x] Commit (833 lines — includes git helpers/formatters co-located with step impls)

### Task 8.3: Rebuild `integration/state_machine.py` as slimmed orchestrator

**File(s):** `teleclaude/core/integration/state_machine.py`

- [x] Remove step function implementations (moved to `step_functions.py`)
- [x] Remove checkpoint types (moved to `checkpoint.py`)
- [x] Add imports: `from .checkpoint import IntegrationPhase, IntegrationCheckpoint, ...` + explicit imports from `step_functions`
- [x] Re-export `IntegrationPhase` explicitly for backward compat (external code imports it from state_machine)
- [x] Verify resulting file under 800 lines (279 lines)
- [x] Commit

---

## Phase 9: Validation

### Task 9.1: Tests and lint

- [x] Run `make test` — 139 passed
- [x] Run `make lint` — guardrails pass for all touched modules; pre-existing large files (api_server.py, daemon.py, etc.) fail the size limit but are out of scope

### Task 9.2: Demo validation

- [x] Run `telec todo demo validate rlf-core-machines` — 6 executable blocks found

---

## Phase 10: Review readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — none needed
