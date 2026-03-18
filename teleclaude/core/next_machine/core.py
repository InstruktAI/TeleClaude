"""Next Machine backward-compatible re-export facade.

All implementations live in focused sub-modules. This module keeps historic
imports from ``teleclaude.core.next_machine.core`` working by lazily resolving
symbols from their owning modules.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_MODULE_EXPORTS: dict[str, list[str]] = {
    "teleclaude.core.next_machine._types": [
        "_PREP_INPUT_FILES",
        "_PREP_ROOT_INPUT_FILES",
        "_PREP_STATE_VERSION",
        "_PREPARE_LOOP_LIMIT",
        "_SINGLE_FLIGHT_GUARD",
        "_WORKTREE_PREP_STATE_REL",
        "DEFAULT_MAX_REVIEW_ROUNDS",
        "DEFAULT_STATE",
        "DOR_READY_THRESHOLD",
        "FINDING_ID_PATTERN",
        "NEXT_WORK_PHASE_LOG",
        "PAREN_OPEN",
        "REVIEW_APPROVE_MARKER",
        "REVIEW_DIFF_NOTE",
        "SCRIPTS_KEY",
        "CreativePhase",
        "DeliveredDict",
        "DeliveredEntry",
        "EnsureWorktreeResult",
        "FinalizeState",
        "ItemPhase",
        "PhaseName",
        "PhaseStatus",
        "PreparePhase",
        "RoadmapDict",
        "RoadmapEntry",
        "StateScalar",
        "StateValue",
        "WorktreePrepDecision",
        "WorktreeScript",
    ],
    "teleclaude.core.next_machine.build_gates": [
        "_count_test_failures",
        "_extract_checklist_section",
        "_is_review_findings_template",
        "_is_scaffold_template",
        "check_file_has_content",
        "format_build_gate_failure",
        "run_build_gates",
        "verify_artifacts",
    ],
    "teleclaude.core.next_machine.create": ["next_create"],
    "teleclaude.core.next_machine.delivery": [
        "_delivered_path",
        "_run_git_cmd",
        "cleanup_delivered_slug",
        "deliver_to_delivered",
        "load_delivered",
        "load_delivered_slugs",
        "save_delivered",
        "sweep_completed_groups",
    ],
    "teleclaude.core.next_machine.git_ops": [
        "_dirty_paths",
        "_has_meaningful_diff",
        "_merge_origin_main_into_worktree",
        "build_git_hook_env",
        "compose_agent_guidance",
        "get_stash_entries",
        "has_git_stash_entries",
        "has_uncommitted_changes",
        "read_text_async",
        "write_text_async",
    ],
    "teleclaude.core.next_machine.icebox": [
        "_icebox_dir",
        "_icebox_path",
        "clean_dependency_references",
        "freeze_to_icebox",
        "load_icebox",
        "load_icebox_slugs",
        "migrate_icebox_to_subfolder",
        "remove_from_icebox",
        "save_icebox",
        "unfreeze_from_icebox",
    ],
    "teleclaude.core.next_machine.output_formatting": [
        "POST_COMPLETION",
        "format_error",
        "format_finalize_handoff_complete",
        "format_prepared",
        "format_stash_debt",
        "format_tool_call",
        "format_uncommitted_changes",
    ],
    "teleclaude.core.next_machine.prepare": ["next_prepare"],
    "teleclaude.core.next_machine.prepare_events": [
        "_derive_prepare_phase",
        "_emit_prepare_event",
        "_has_test_spec_artifacts",
        "_is_artifact_produced_v2",
        "invalidate_stale_preparations",
    ],
    "teleclaude.core.next_machine.prepare_steps": [
        "_prepare_dispatch",
        "_prepare_step_requirements_review",
    ],
    "teleclaude.core.next_machine.roadmap": [
        "_roadmap_path",
        "add_to_roadmap",
        "check_dependencies_satisfied",
        "detect_circular_dependency",
        "load_roadmap",
        "load_roadmap_deps",
        "load_roadmap_slugs",
        "move_in_roadmap",
        "remove_from_roadmap",
        "save_roadmap",
        "slug_in_roadmap",
    ],
    "teleclaude.core.next_machine.slug_resolution": [
        "_find_next_prepare_slug",
        "check_file_exists",
        "get_item_phase",
        "is_ready_for_work",
        "resolve_canonical_project_root",
        "resolve_first_runnable_holder_child",
        "resolve_holder_children",
        "resolve_slug",
        "resolve_slug_async",
        "set_item_phase",
    ],
    "teleclaude.core.next_machine.state_io": [
        "_DEEP_MERGE_KEYS",
        "_PREPARE_ARTIFACT_PHASES",
        "_PREPARE_PHASE_VALUES",
        "_PREPARE_VERDICT_PHASES",
        "_PREPARE_VERDICT_VALUES",
        "_deep_merge_state",
        "_extract_finding_ids",
        "_file_sha256",
        "_get_finalize_state",
        "_get_head_commit",
        "_get_ref_commit",
        "_get_remote_branch_head",
        "_is_review_round_limit_reached",
        "_mark_finalize_handed_off",
        "_normalize_finalize_state",
        "_review_scope_note",
        "_run_git_prepare",
        *(
            "check_review_status get_state_path has_pending_deferrals is_bug_todo is_build_complete "
            "is_review_approved is_review_changes_requested mark_finalize_ready mark_phase "
            "mark_prepare_artifact mark_prepare_phase mark_prepare_verdict read_breakdown_state "
            "read_phase_state read_text_sync write_breakdown_state write_phase_state write_text_sync"
        ).split(),
    ],
    "teleclaude.core.next_machine.work": ["next_work"],
    "teleclaude.core.next_machine.worktrees": [
        "_compute_prep_inputs_digest",
        "_create_or_attach_worktree",
        "_decide_worktree_prep",
        "_ensure_todo_on_remote_main",
        "_prepare_worktree",
        "_read_worktree_prep_state",
        "_worktree_prep_state_path",
        "_write_worktree_prep_state",
        "ensure_worktree_with_policy",
        "ensure_worktree_with_policy_async",
    ],
}

_NAME_TO_MODULE = {export_name: module_name for module_name, names in _MODULE_EXPORTS.items() for export_name in names}
_MODULE_CACHE: dict[str, ModuleType] = {}
__all__ = [name for names in _MODULE_EXPORTS.values() for name in names]


def _load_module(module_name: str) -> ModuleType:
    """Load and cache an export source module."""
    module = _MODULE_CACHE.get(module_name)
    if module is None:
        module = import_module(module_name)
        _MODULE_CACHE[module_name] = module
    return module


def __getattr__(name: str) -> object:
    """Resolve re-exported names lazily from their source modules."""
    module_name = _NAME_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(_load_module(module_name), name)


def __dir__() -> list[str]:
    """Expose the compatibility export surface to introspection tools."""
    return sorted(set(globals()) | set(__all__))
