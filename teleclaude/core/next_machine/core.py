"""Next Machine — backward-compatible re-export facade.

All implementations live in focused sub-modules. This file exists solely
for backward compatibility so that existing imports from
``teleclaude.core.next_machine.core`` continue to resolve.

Do NOT add new code here — implement in the appropriate sub-module.
"""

from __future__ import annotations

from teleclaude.core.next_machine._types import (
    _PREP_INPUT_FILES as _PREP_INPUT_FILES,
)
from teleclaude.core.next_machine._types import (
    _PREP_ROOT_INPUT_FILES as _PREP_ROOT_INPUT_FILES,
)
from teleclaude.core.next_machine._types import (
    _PREP_STATE_VERSION as _PREP_STATE_VERSION,
)
from teleclaude.core.next_machine._types import (
    _PREPARE_LOOP_LIMIT as _PREPARE_LOOP_LIMIT,
)
from teleclaude.core.next_machine._types import (
    _SINGLE_FLIGHT_GUARD as _SINGLE_FLIGHT_GUARD,
)
from teleclaude.core.next_machine._types import (
    _WORKTREE_PREP_STATE_REL as _WORKTREE_PREP_STATE_REL,
)

# ── types & constants ──────────────────────────────────────────────────────────
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS as DEFAULT_MAX_REVIEW_ROUNDS,
)
from teleclaude.core.next_machine._types import (
    DEFAULT_STATE as DEFAULT_STATE,
)
from teleclaude.core.next_machine._types import (
    DOR_READY_THRESHOLD as DOR_READY_THRESHOLD,
)
from teleclaude.core.next_machine._types import (
    FINDING_ID_PATTERN as FINDING_ID_PATTERN,
)
from teleclaude.core.next_machine._types import (
    NEXT_WORK_PHASE_LOG as NEXT_WORK_PHASE_LOG,
)
from teleclaude.core.next_machine._types import (
    PAREN_OPEN as PAREN_OPEN,
)
from teleclaude.core.next_machine._types import (
    REVIEW_APPROVE_MARKER as REVIEW_APPROVE_MARKER,
)
from teleclaude.core.next_machine._types import (
    REVIEW_DIFF_NOTE as REVIEW_DIFF_NOTE,
)
from teleclaude.core.next_machine._types import (
    SCRIPTS_KEY as SCRIPTS_KEY,
)
from teleclaude.core.next_machine._types import (
    CreativePhase as CreativePhase,
)
from teleclaude.core.next_machine._types import (
    DeliveredDict as DeliveredDict,
)
from teleclaude.core.next_machine._types import (
    DeliveredEntry as DeliveredEntry,
)
from teleclaude.core.next_machine._types import (
    EnsureWorktreeResult as EnsureWorktreeResult,
)
from teleclaude.core.next_machine._types import (
    FinalizeState as FinalizeState,
)
from teleclaude.core.next_machine._types import (
    ItemPhase as ItemPhase,
)
from teleclaude.core.next_machine._types import (
    PhaseName as PhaseName,
)
from teleclaude.core.next_machine._types import (
    PhaseStatus as PhaseStatus,
)
from teleclaude.core.next_machine._types import (
    PreparePhase as PreparePhase,
)
from teleclaude.core.next_machine._types import (
    RoadmapDict as RoadmapDict,
)
from teleclaude.core.next_machine._types import (
    RoadmapEntry as RoadmapEntry,
)
from teleclaude.core.next_machine._types import (
    StateScalar as StateScalar,
)
from teleclaude.core.next_machine._types import (
    StateValue as StateValue,
)
from teleclaude.core.next_machine._types import (
    WorktreePrepDecision as WorktreePrepDecision,
)
from teleclaude.core.next_machine._types import (
    WorktreeScript as WorktreeScript,
)

# ── build gates & artifact verification ───────────────────────────────────────
from teleclaude.core.next_machine.build_gates import (
    _count_test_failures as _count_test_failures,
)
from teleclaude.core.next_machine.build_gates import (
    _extract_checklist_section as _extract_checklist_section,
)
from teleclaude.core.next_machine.build_gates import (
    _is_review_findings_template as _is_review_findings_template,
)
from teleclaude.core.next_machine.build_gates import (
    _is_scaffold_template as _is_scaffold_template,
)
from teleclaude.core.next_machine.build_gates import (
    check_file_has_content as check_file_has_content,
)
from teleclaude.core.next_machine.build_gates import (
    format_build_gate_failure as format_build_gate_failure,
)
from teleclaude.core.next_machine.build_gates import (
    run_build_gates as run_build_gates,
)
from teleclaude.core.next_machine.build_gates import (
    verify_artifacts as verify_artifacts,
)

# ── top-level state machines ───────────────────────────────────────────────────
from teleclaude.core.next_machine.create import next_create as next_create

# ── delivery ───────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.delivery import (
    _delivered_path as _delivered_path,
)
from teleclaude.core.next_machine.delivery import (
    _run_git_cmd as _run_git_cmd,
)
from teleclaude.core.next_machine.delivery import (
    cleanup_delivered_slug as cleanup_delivered_slug,
)
from teleclaude.core.next_machine.delivery import (
    deliver_to_delivered as deliver_to_delivered,
)
from teleclaude.core.next_machine.delivery import (
    load_delivered as load_delivered,
)
from teleclaude.core.next_machine.delivery import (
    load_delivered_slugs as load_delivered_slugs,
)
from teleclaude.core.next_machine.delivery import (
    save_delivered as save_delivered,
)
from teleclaude.core.next_machine.delivery import (
    sweep_completed_groups as sweep_completed_groups,
)

# ── git operations ─────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.git_ops import (
    _dirty_paths as _dirty_paths,
)
from teleclaude.core.next_machine.git_ops import (
    _has_meaningful_diff as _has_meaningful_diff,
)
from teleclaude.core.next_machine.git_ops import (
    _merge_origin_main_into_worktree as _merge_origin_main_into_worktree,
)
from teleclaude.core.next_machine.git_ops import (
    build_git_hook_env as build_git_hook_env,
)
from teleclaude.core.next_machine.git_ops import (
    compose_agent_guidance as compose_agent_guidance,
)
from teleclaude.core.next_machine.git_ops import (
    get_stash_entries as get_stash_entries,
)
from teleclaude.core.next_machine.git_ops import (
    has_git_stash_entries as has_git_stash_entries,
)
from teleclaude.core.next_machine.git_ops import (
    has_uncommitted_changes as has_uncommitted_changes,
)
from teleclaude.core.next_machine.git_ops import (
    read_text_async as read_text_async,
)
from teleclaude.core.next_machine.git_ops import (
    write_text_async as write_text_async,
)

# ── icebox ─────────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.icebox import (
    _icebox_dir as _icebox_dir,
)
from teleclaude.core.next_machine.icebox import (
    _icebox_path as _icebox_path,
)
from teleclaude.core.next_machine.icebox import (
    clean_dependency_references as clean_dependency_references,
)
from teleclaude.core.next_machine.icebox import (
    freeze_to_icebox as freeze_to_icebox,
)
from teleclaude.core.next_machine.icebox import (
    load_icebox as load_icebox,
)
from teleclaude.core.next_machine.icebox import (
    load_icebox_slugs as load_icebox_slugs,
)
from teleclaude.core.next_machine.icebox import (
    migrate_icebox_to_subfolder as migrate_icebox_to_subfolder,
)
from teleclaude.core.next_machine.icebox import (
    remove_from_icebox as remove_from_icebox,
)
from teleclaude.core.next_machine.icebox import (
    save_icebox as save_icebox,
)
from teleclaude.core.next_machine.icebox import (
    unfreeze_from_icebox as unfreeze_from_icebox,
)

# ── output formatting ──────────────────────────────────────────────────────────
from teleclaude.core.next_machine.output_formatting import (
    POST_COMPLETION as POST_COMPLETION,
)
from teleclaude.core.next_machine.output_formatting import (
    format_error as format_error,
)
from teleclaude.core.next_machine.output_formatting import (
    format_finalize_handoff_complete as format_finalize_handoff_complete,
)
from teleclaude.core.next_machine.output_formatting import (
    format_prepared as format_prepared,
)
from teleclaude.core.next_machine.output_formatting import (
    format_stash_debt as format_stash_debt,
)
from teleclaude.core.next_machine.output_formatting import (
    format_tool_call as format_tool_call,
)
from teleclaude.core.next_machine.output_formatting import (
    format_uncommitted_changes as format_uncommitted_changes,
)
from teleclaude.core.next_machine.prepare import next_prepare as next_prepare

# ── prepare events & phase derivation ─────────────────────────────────────────
from teleclaude.core.next_machine.prepare_events import (
    _derive_prepare_phase as _derive_prepare_phase,
)
from teleclaude.core.next_machine.prepare_events import (
    _emit_prepare_event as _emit_prepare_event,
)
from teleclaude.core.next_machine.prepare_events import (
    _has_test_spec_artifacts as _has_test_spec_artifacts,
)
from teleclaude.core.next_machine.prepare_events import (
    _is_artifact_produced_v2 as _is_artifact_produced_v2,
)
from teleclaude.core.next_machine.prepare_events import (
    invalidate_stale_preparations as invalidate_stale_preparations,
)

# ── prepare step dispatch ──────────────────────────────────────────────────────
from teleclaude.core.next_machine.prepare_steps import (
    _prepare_dispatch as _prepare_dispatch,
)
from teleclaude.core.next_machine.prepare_steps import (
    _prepare_step_requirements_review as _prepare_step_requirements_review,
)

# ── roadmap ────────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.roadmap import (
    _roadmap_path as _roadmap_path,
)
from teleclaude.core.next_machine.roadmap import (
    add_to_roadmap as add_to_roadmap,
)
from teleclaude.core.next_machine.roadmap import (
    check_dependencies_satisfied as check_dependencies_satisfied,
)
from teleclaude.core.next_machine.roadmap import (
    detect_circular_dependency as detect_circular_dependency,
)
from teleclaude.core.next_machine.roadmap import (
    load_roadmap as load_roadmap,
)
from teleclaude.core.next_machine.roadmap import (
    load_roadmap_deps as load_roadmap_deps,
)
from teleclaude.core.next_machine.roadmap import (
    load_roadmap_slugs as load_roadmap_slugs,
)
from teleclaude.core.next_machine.roadmap import (
    move_in_roadmap as move_in_roadmap,
)
from teleclaude.core.next_machine.roadmap import (
    remove_from_roadmap as remove_from_roadmap,
)
from teleclaude.core.next_machine.roadmap import (
    save_roadmap as save_roadmap,
)
from teleclaude.core.next_machine.roadmap import (
    slug_in_roadmap as slug_in_roadmap,
)

# ── slug resolution ────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.slug_resolution import (
    _find_next_prepare_slug as _find_next_prepare_slug,
)
from teleclaude.core.next_machine.slug_resolution import (
    check_file_exists as check_file_exists,
)
from teleclaude.core.next_machine.slug_resolution import (
    get_item_phase as get_item_phase,
)
from teleclaude.core.next_machine.slug_resolution import (
    is_ready_for_work as is_ready_for_work,
)
from teleclaude.core.next_machine.slug_resolution import (
    resolve_canonical_project_root as resolve_canonical_project_root,
)
from teleclaude.core.next_machine.slug_resolution import (
    resolve_first_runnable_holder_child as resolve_first_runnable_holder_child,
)
from teleclaude.core.next_machine.slug_resolution import (
    resolve_holder_children as resolve_holder_children,
)
from teleclaude.core.next_machine.slug_resolution import (
    resolve_slug as resolve_slug,
)
from teleclaude.core.next_machine.slug_resolution import (
    resolve_slug_async as resolve_slug_async,
)
from teleclaude.core.next_machine.slug_resolution import (
    set_item_phase as set_item_phase,
)

# ── state I/O ──────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.state_io import (
    _DEEP_MERGE_KEYS as _DEEP_MERGE_KEYS,
)
from teleclaude.core.next_machine.state_io import (
    _PREPARE_PHASE_VALUES as _PREPARE_PHASE_VALUES,
)
from teleclaude.core.next_machine.state_io import (
    _PREPARE_VERDICT_PHASES as _PREPARE_VERDICT_PHASES,
)
from teleclaude.core.next_machine.state_io import (
    _PREPARE_VERDICT_VALUES as _PREPARE_VERDICT_VALUES,
)
from teleclaude.core.next_machine.state_io import (
    _deep_merge_state as _deep_merge_state,
)
from teleclaude.core.next_machine.state_io import (
    _extract_finding_ids as _extract_finding_ids,
)
from teleclaude.core.next_machine.state_io import (
    _file_sha256 as _file_sha256,
)
from teleclaude.core.next_machine.state_io import (
    _get_finalize_state as _get_finalize_state,
)
from teleclaude.core.next_machine.state_io import (
    _get_head_commit as _get_head_commit,
)
from teleclaude.core.next_machine.state_io import (
    _get_ref_commit as _get_ref_commit,
)
from teleclaude.core.next_machine.state_io import (
    _get_remote_branch_head as _get_remote_branch_head,
)
from teleclaude.core.next_machine.state_io import (
    _is_review_round_limit_reached as _is_review_round_limit_reached,
)
from teleclaude.core.next_machine.state_io import (
    _mark_finalize_handed_off as _mark_finalize_handed_off,
)
from teleclaude.core.next_machine.state_io import (
    _normalize_finalize_state as _normalize_finalize_state,
)
from teleclaude.core.next_machine.state_io import (
    _review_scope_note as _review_scope_note,
)
from teleclaude.core.next_machine.state_io import (
    _run_git_prepare as _run_git_prepare,
)
from teleclaude.core.next_machine.state_io import (
    check_review_status as check_review_status,
)
from teleclaude.core.next_machine.state_io import (
    get_state_path as get_state_path,
)
from teleclaude.core.next_machine.state_io import (
    has_pending_deferrals as has_pending_deferrals,
)
from teleclaude.core.next_machine.state_io import (
    is_bug_todo as is_bug_todo,
)
from teleclaude.core.next_machine.state_io import (
    is_build_complete as is_build_complete,
)
from teleclaude.core.next_machine.state_io import (
    is_review_approved as is_review_approved,
)
from teleclaude.core.next_machine.state_io import (
    is_review_changes_requested as is_review_changes_requested,
)
from teleclaude.core.next_machine.state_io import (
    mark_finalize_ready as mark_finalize_ready,
)
from teleclaude.core.next_machine.state_io import (
    mark_phase as mark_phase,
)
from teleclaude.core.next_machine.state_io import (
    mark_prepare_phase as mark_prepare_phase,
)
from teleclaude.core.next_machine.state_io import (
    mark_prepare_verdict as mark_prepare_verdict,
)
from teleclaude.core.next_machine.state_io import (
    read_breakdown_state as read_breakdown_state,
)
from teleclaude.core.next_machine.state_io import (
    read_phase_state as read_phase_state,
)
from teleclaude.core.next_machine.state_io import (
    read_text_sync as read_text_sync,
)
from teleclaude.core.next_machine.state_io import (
    write_breakdown_state as write_breakdown_state,
)
from teleclaude.core.next_machine.state_io import (
    write_phase_state as write_phase_state,
)
from teleclaude.core.next_machine.state_io import (
    write_text_sync as write_text_sync,
)
from teleclaude.core.next_machine.work import next_work as next_work

# ── worktree management ────────────────────────────────────────────────────────
from teleclaude.core.next_machine.worktrees import (
    _compute_prep_inputs_digest as _compute_prep_inputs_digest,
)
from teleclaude.core.next_machine.worktrees import (
    _create_or_attach_worktree as _create_or_attach_worktree,
)
from teleclaude.core.next_machine.worktrees import (
    _decide_worktree_prep as _decide_worktree_prep,
)
from teleclaude.core.next_machine.worktrees import (
    _ensure_todo_on_remote_main as _ensure_todo_on_remote_main,
)
from teleclaude.core.next_machine.worktrees import (
    _prepare_worktree as _prepare_worktree,
)
from teleclaude.core.next_machine.worktrees import (
    _read_worktree_prep_state as _read_worktree_prep_state,
)
from teleclaude.core.next_machine.worktrees import (
    _worktree_prep_state_path as _worktree_prep_state_path,
)
from teleclaude.core.next_machine.worktrees import (
    _write_worktree_prep_state as _write_worktree_prep_state,
)
from teleclaude.core.next_machine.worktrees import (
    ensure_worktree_with_policy as ensure_worktree_with_policy,
)
from teleclaude.core.next_machine.worktrees import (
    ensure_worktree_with_policy_async as ensure_worktree_with_policy_async,
)
