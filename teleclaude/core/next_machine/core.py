"""Next Machine — backward-compatible re-export facade.

All implementations live in focused sub-modules. This file exists solely
for backward compatibility so that existing imports from
``teleclaude.core.next_machine.core`` continue to resolve.

Do NOT add new code here — implement in the appropriate sub-module.
"""

from __future__ import annotations

# ── types & constants ──────────────────────────────────────────────────────────
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS as DEFAULT_MAX_REVIEW_ROUNDS,
    DEFAULT_STATE as DEFAULT_STATE,
    DOR_READY_THRESHOLD as DOR_READY_THRESHOLD,
    FINDING_ID_PATTERN as FINDING_ID_PATTERN,
    NEXT_WORK_PHASE_LOG as NEXT_WORK_PHASE_LOG,
    PAREN_OPEN as PAREN_OPEN,
    REVIEW_APPROVE_MARKER as REVIEW_APPROVE_MARKER,
    REVIEW_DIFF_NOTE as REVIEW_DIFF_NOTE,
    SCRIPTS_KEY as SCRIPTS_KEY,
    CreativePhase as CreativePhase,
    DeliveredDict as DeliveredDict,
    DeliveredEntry as DeliveredEntry,
    EnsureWorktreeResult as EnsureWorktreeResult,
    FinalizeState as FinalizeState,
    ItemPhase as ItemPhase,
    PhaseName as PhaseName,
    PhaseStatus as PhaseStatus,
    PreparePhase as PreparePhase,
    RoadmapDict as RoadmapDict,
    RoadmapEntry as RoadmapEntry,
    StateScalar as StateScalar,
    StateValue as StateValue,
    WorktreePrepDecision as WorktreePrepDecision,
    WorktreeScript as WorktreeScript,
    _PREP_INPUT_FILES as _PREP_INPUT_FILES,
    _PREP_ROOT_INPUT_FILES as _PREP_ROOT_INPUT_FILES,
    _PREP_STATE_VERSION as _PREP_STATE_VERSION,
    _PREPARE_LOOP_LIMIT as _PREPARE_LOOP_LIMIT,
    _SINGLE_FLIGHT_GUARD as _SINGLE_FLIGHT_GUARD,
    _WORKTREE_PREP_STATE_REL as _WORKTREE_PREP_STATE_REL,
)

# ── state I/O ──────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.state_io import (
    _DEEP_MERGE_KEYS as _DEEP_MERGE_KEYS,
    _PREPARE_PHASE_VALUES as _PREPARE_PHASE_VALUES,
    _PREPARE_VERDICT_PHASES as _PREPARE_VERDICT_PHASES,
    _PREPARE_VERDICT_VALUES as _PREPARE_VERDICT_VALUES,
    _deep_merge_state as _deep_merge_state,
    _extract_finding_ids as _extract_finding_ids,
    _file_sha256 as _file_sha256,
    _get_finalize_state as _get_finalize_state,
    _get_head_commit as _get_head_commit,
    _get_ref_commit as _get_ref_commit,
    _get_remote_branch_head as _get_remote_branch_head,
    _is_review_round_limit_reached as _is_review_round_limit_reached,
    _mark_finalize_handed_off as _mark_finalize_handed_off,
    _normalize_finalize_state as _normalize_finalize_state,
    _review_scope_note as _review_scope_note,
    _run_git_prepare as _run_git_prepare,
    check_review_status as check_review_status,
    get_state_path as get_state_path,
    has_pending_deferrals as has_pending_deferrals,
    is_build_complete as is_build_complete,
    is_bug_todo as is_bug_todo,
    is_review_approved as is_review_approved,
    is_review_changes_requested as is_review_changes_requested,
    mark_finalize_ready as mark_finalize_ready,
    mark_phase as mark_phase,
    mark_prepare_phase as mark_prepare_phase,
    mark_prepare_verdict as mark_prepare_verdict,
    read_breakdown_state as read_breakdown_state,
    read_phase_state as read_phase_state,
    read_text_sync as read_text_sync,
    write_breakdown_state as write_breakdown_state,
    write_phase_state as write_phase_state,
    write_text_sync as write_text_sync,
)

# ── roadmap ────────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.roadmap import (
    _roadmap_path as _roadmap_path,
    add_to_roadmap as add_to_roadmap,
    check_dependencies_satisfied as check_dependencies_satisfied,
    detect_circular_dependency as detect_circular_dependency,
    load_roadmap as load_roadmap,
    load_roadmap_deps as load_roadmap_deps,
    load_roadmap_slugs as load_roadmap_slugs,
    move_in_roadmap as move_in_roadmap,
    remove_from_roadmap as remove_from_roadmap,
    save_roadmap as save_roadmap,
    slug_in_roadmap as slug_in_roadmap,
)

# ── icebox ─────────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.icebox import (
    _icebox_dir as _icebox_dir,
    _icebox_path as _icebox_path,
    clean_dependency_references as clean_dependency_references,
    freeze_to_icebox as freeze_to_icebox,
    load_icebox as load_icebox,
    load_icebox_slugs as load_icebox_slugs,
    migrate_icebox_to_subfolder as migrate_icebox_to_subfolder,
    remove_from_icebox as remove_from_icebox,
    save_icebox as save_icebox,
    unfreeze_from_icebox as unfreeze_from_icebox,
)

# ── delivery ───────────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.delivery import (
    _delivered_path as _delivered_path,
    _run_git_cmd as _run_git_cmd,
    cleanup_delivered_slug as cleanup_delivered_slug,
    deliver_to_delivered as deliver_to_delivered,
    load_delivered as load_delivered,
    load_delivered_slugs as load_delivered_slugs,
    save_delivered as save_delivered,
    sweep_completed_groups as sweep_completed_groups,
)

# ── git operations ─────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.git_ops import (
    _dirty_paths as _dirty_paths,
    _has_meaningful_diff as _has_meaningful_diff,
    _merge_origin_main_into_worktree as _merge_origin_main_into_worktree,
    build_git_hook_env as build_git_hook_env,
    compose_agent_guidance as compose_agent_guidance,
    get_stash_entries as get_stash_entries,
    has_git_stash_entries as has_git_stash_entries,
    has_uncommitted_changes as has_uncommitted_changes,
    read_text_async as read_text_async,
    write_text_async as write_text_async,
)

# ── slug resolution ────────────────────────────────────────────────────────────
from teleclaude.core.next_machine.slug_resolution import (
    _find_next_prepare_slug as _find_next_prepare_slug,
    check_file_exists as check_file_exists,
    get_item_phase as get_item_phase,
    is_ready_for_work as is_ready_for_work,
    resolve_canonical_project_root as resolve_canonical_project_root,
    resolve_first_runnable_holder_child as resolve_first_runnable_holder_child,
    resolve_holder_children as resolve_holder_children,
    resolve_slug as resolve_slug,
    resolve_slug_async as resolve_slug_async,
    set_item_phase as set_item_phase,
)

# ── output formatting ──────────────────────────────────────────────────────────
from teleclaude.core.next_machine.output_formatting import (
    POST_COMPLETION as POST_COMPLETION,
    format_error as format_error,
    format_finalize_handoff_complete as format_finalize_handoff_complete,
    format_prepared as format_prepared,
    format_stash_debt as format_stash_debt,
    format_tool_call as format_tool_call,
    format_uncommitted_changes as format_uncommitted_changes,
)

# ── build gates & artifact verification ───────────────────────────────────────
from teleclaude.core.next_machine.build_gates import (
    _count_test_failures as _count_test_failures,
    _extract_checklist_section as _extract_checklist_section,
    _is_review_findings_template as _is_review_findings_template,
    _is_scaffold_template as _is_scaffold_template,
    check_file_has_content as check_file_has_content,
    format_build_gate_failure as format_build_gate_failure,
    run_build_gates as run_build_gates,
    verify_artifacts as verify_artifacts,
)

# ── worktree management ────────────────────────────────────────────────────────
from teleclaude.core.next_machine.worktrees import (
    _compute_prep_inputs_digest as _compute_prep_inputs_digest,
    _create_or_attach_worktree as _create_or_attach_worktree,
    _decide_worktree_prep as _decide_worktree_prep,
    _ensure_todo_on_remote_main as _ensure_todo_on_remote_main,
    _prepare_worktree as _prepare_worktree,
    _read_worktree_prep_state as _read_worktree_prep_state,
    _worktree_prep_state_path as _worktree_prep_state_path,
    _write_worktree_prep_state as _write_worktree_prep_state,
    ensure_worktree_with_policy as ensure_worktree_with_policy,
    ensure_worktree_with_policy_async as ensure_worktree_with_policy_async,
)

# ── prepare events & phase derivation ─────────────────────────────────────────
from teleclaude.core.next_machine.prepare_events import (
    _derive_prepare_phase as _derive_prepare_phase,
    _emit_prepare_event as _emit_prepare_event,
    _has_test_spec_artifacts as _has_test_spec_artifacts,
    _is_artifact_produced_v2 as _is_artifact_produced_v2,
    invalidate_stale_preparations as invalidate_stale_preparations,
)

# ── prepare step dispatch ──────────────────────────────────────────────────────
from teleclaude.core.next_machine.prepare_steps import (
    _prepare_dispatch as _prepare_dispatch,
    _prepare_step_requirements_review as _prepare_step_requirements_review,
)

# ── top-level state machines ───────────────────────────────────────────────────
from teleclaude.core.next_machine.create import next_create as next_create
from teleclaude.core.next_machine.prepare import next_prepare as next_prepare
from teleclaude.core.next_machine.work import next_work as next_work

