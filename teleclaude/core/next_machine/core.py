"""Next Machine — backward-compatible re-export facade.

All implementations live in focused sub-modules. This file exists solely
for backward compatibility so that existing imports from
``teleclaude.core.next_machine.core`` continue to resolve.

Do NOT add new code here — implement in the appropriate sub-module.
"""

from __future__ import annotations

# ── types & constants ──────────────────────────────────────────────────────────
from teleclaude.core.next_machine._types import _PREP_INPUT_FILES as _PREP_INPUT_FILES
from teleclaude.core.next_machine._types import _PREP_ROOT_INPUT_FILES as _PREP_ROOT_INPUT_FILES
from teleclaude.core.next_machine._types import _PREP_STATE_VERSION as _PREP_STATE_VERSION
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT as _PREPARE_LOOP_LIMIT
from teleclaude.core.next_machine._types import _SINGLE_FLIGHT_GUARD as _SINGLE_FLIGHT_GUARD
from teleclaude.core.next_machine._types import _WORKTREE_PREP_STATE_REL as _WORKTREE_PREP_STATE_REL
from teleclaude.core.next_machine._types import DEFAULT_MAX_REVIEW_ROUNDS as DEFAULT_MAX_REVIEW_ROUNDS
from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD as DOR_READY_THRESHOLD
from teleclaude.core.next_machine._types import NEXT_WORK_PHASE_LOG as NEXT_WORK_PHASE_LOG
from teleclaude.core.next_machine._types import PAREN_OPEN as PAREN_OPEN
from teleclaude.core.next_machine._types import REVIEW_DIFF_NOTE as REVIEW_DIFF_NOTE
from teleclaude.core.next_machine._types import SCRIPTS_KEY as SCRIPTS_KEY
from teleclaude.core.next_machine._types import CreativePhase as CreativePhase
from teleclaude.core.next_machine._types import EnsureWorktreeResult as EnsureWorktreeResult
from teleclaude.core.next_machine._types import FinalizeState as FinalizeState
from teleclaude.core.next_machine._types import ItemPhase as ItemPhase
from teleclaude.core.next_machine._types import PhaseName as PhaseName
from teleclaude.core.next_machine._types import PhaseStatus as PhaseStatus
from teleclaude.core.next_machine._types import PreparePhase as PreparePhase
from teleclaude.core.next_machine._types import StateScalar as StateScalar
from teleclaude.core.next_machine._types import StateValue as StateValue
from teleclaude.core.next_machine._types import WorktreePrepDecision as WorktreePrepDecision
from teleclaude.core.next_machine._types import WorktreeScript as WorktreeScript
from teleclaude.core.next_machine._types import default_state as default_state

# ── build gates & artifact verification ───────────────────────────────────────
from teleclaude.core.next_machine.build_gates import _count_test_failures as _count_test_failures
from teleclaude.core.next_machine.build_gates import format_build_gate_failure as format_build_gate_failure
from teleclaude.core.next_machine.build_gates import run_build_gates as run_build_gates

# ── top-level state machines ───────────────────────────────────────────────────
from teleclaude.core.next_machine.create import next_create as next_create

# ── delivery ───────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.delivery import _run_git_cmd as _run_git_cmd
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug as cleanup_delivered_slug

# ── dependency graph utilities (pure logic, no filesystem) ────────────────────
from teleclaude.core.next_machine.dep_graph import detect_circular_dependency as detect_circular_dependency

# ── git operations ─────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.git_ops import _dirty_paths as _dirty_paths
from teleclaude.core.next_machine.git_ops import _has_meaningful_diff as _has_meaningful_diff
from teleclaude.core.next_machine.git_ops import _merge_origin_main_into_worktree as _merge_origin_main_into_worktree
from teleclaude.core.next_machine.git_ops import build_git_hook_env as build_git_hook_env
from teleclaude.core.next_machine.git_ops import compose_agent_guidance as compose_agent_guidance
from teleclaude.core.next_machine.git_ops import get_stash_entries as get_stash_entries
from teleclaude.core.next_machine.git_ops import has_git_stash_entries as has_git_stash_entries
from teleclaude.core.next_machine.git_ops import has_uncommitted_changes as has_uncommitted_changes
from teleclaude.core.next_machine.git_ops import read_text_async as read_text_async
from teleclaude.core.next_machine.git_ops import write_text_async as write_text_async

# ── output formatting ──────────────────────────────────────────────────────────
from teleclaude.core.next_machine.output_formatting import format_error as format_error
from teleclaude.core.next_machine.output_formatting import (
    format_finalize_handoff_complete as format_finalize_handoff_complete,
)
from teleclaude.core.next_machine.output_formatting import format_prepared as format_prepared
from teleclaude.core.next_machine.output_formatting import format_stash_debt as format_stash_debt
from teleclaude.core.next_machine.output_formatting import format_tool_call as format_tool_call
from teleclaude.core.next_machine.output_formatting import format_uncommitted_changes as format_uncommitted_changes
from teleclaude.core.next_machine.prepare import next_prepare as next_prepare

# ── prepare events ────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event as _emit_prepare_event
from teleclaude.core.next_machine.prepare_events import invalidate_stale_preparations as invalidate_stale_preparations

# ── prepare step dispatch ──────────────────────────────────────────────────────
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch as _prepare_dispatch
from teleclaude.core.next_machine.prepare_steps import (
    _prepare_step_requirements_review as _prepare_step_requirements_review,
)

# ── slug resolution ────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.slug_resolution import get_item_phase as get_item_phase
from teleclaude.core.next_machine.slug_resolution import (
    resolve_canonical_project_root as resolve_canonical_project_root,
)
from teleclaude.core.next_machine.slug_resolution import resolve_slug_async as resolve_slug_async
from teleclaude.core.next_machine.slug_resolution import set_item_phase as set_item_phase
from teleclaude.core.next_machine.slug_resolution import slug_in_roadmap as slug_in_roadmap

# ── state I/O ──────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.state_io import _BUILD_VERDICT_PHASE as _BUILD_VERDICT_PHASE
from teleclaude.core.next_machine.state_io import _BUILD_VERDICT_VALUES as _BUILD_VERDICT_VALUES
from teleclaude.core.next_machine.state_io import _PREPARE_ARTIFACT_PHASES as _PREPARE_ARTIFACT_PHASES
from teleclaude.core.next_machine.state_io import _PREPARE_VERDICT_PHASES as _PREPARE_VERDICT_PHASES
from teleclaude.core.next_machine.state_io import _PREPARE_VERDICT_VALUES as _PREPARE_VERDICT_VALUES
from teleclaude.core.next_machine.state_io import apply_prepared_state as apply_prepared_state
from teleclaude.core.next_machine.state_io import has_pending_deferrals as has_pending_deferrals
from teleclaude.core.next_machine.state_io import is_bug_todo as is_bug_todo
from teleclaude.core.next_machine.state_io import read_breakdown_state as read_breakdown_state
from teleclaude.core.next_machine.state_io import read_phase_state as read_phase_state
from teleclaude.core.next_machine.state_io import read_text_sync as read_text_sync
from teleclaude.core.next_machine.state_io import stamp_artifact as stamp_artifact
from teleclaude.core.next_machine.state_io import stamp_finalize_ready as stamp_finalize_ready
from teleclaude.core.next_machine.state_io import stamp_verdict as stamp_verdict
from teleclaude.core.next_machine.state_io import write_breakdown_state as write_breakdown_state
from teleclaude.core.next_machine.state_io import write_phase_state as write_phase_state
from teleclaude.core.next_machine.state_io import write_text_sync as write_text_sync
from teleclaude.core.next_machine.work import next_work as next_work

# ── worktree management ────────────────────────────────────────────────────────
from teleclaude.core.next_machine.worktrees import _compute_prep_inputs_digest as _compute_prep_inputs_digest
from teleclaude.core.next_machine.worktrees import _create_or_attach_worktree as _create_or_attach_worktree
from teleclaude.core.next_machine.worktrees import _decide_worktree_prep as _decide_worktree_prep
from teleclaude.core.next_machine.worktrees import _prepare_worktree as _prepare_worktree
from teleclaude.core.next_machine.worktrees import _read_worktree_prep_state as _read_worktree_prep_state
from teleclaude.core.next_machine.worktrees import _worktree_prep_state_path as _worktree_prep_state_path
from teleclaude.core.next_machine.worktrees import _write_worktree_prep_state as _write_worktree_prep_state
from teleclaude.core.next_machine.worktrees import ensure_worktree_with_policy as ensure_worktree_with_policy
from teleclaude.core.next_machine.worktrees import (
    ensure_worktree_with_policy_async as ensure_worktree_with_policy_async,
)
