"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses session_scoping.resolve_workspace and the durable declaration record for
turn-local file attribution, and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

from teleclaude.hooks.checkpoint._composition import (
    _commit_instruction,
    _compose_checkpoint_message,
    _declare_reminder_instruction,
)
from teleclaude.hooks.checkpoint._entry import build_checkpoint_message, get_checkpoint_content
from teleclaude.hooks.checkpoint._evidence import (
    _check_blast_radius,
    _check_companion_drift,
    _command_has_evidence,
    _compute_log_since_window,
    _dedupe_strings,
    _has_commit_evidence,
    _has_evidence,
    _has_evidence_after_index,
    _iter_shell_command_records,
    _last_scope_mutation_index,
    _segment_matches_evidence,
)
from teleclaude.hooks.checkpoint._git import (
    _canonical_tool_name,
    _current_branch,
    _dirty_repo_paths,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _git_diff_names,
    _is_checkpoint_project_supported,
    _is_docs_only,
    _is_no_action_only,
    _normalize_repo_path,
    _segment_tokens,
    _split_shell_segments,
    _transcript_observability,
)
from teleclaude.hooks.checkpoint._heuristics import _post_commit_review_instruction, run_heuristics
from teleclaude.hooks.checkpoint._models import (
    CheckpointContext,
    CheckpointResult,
    TranscriptObservability,
)
from teleclaude.session_scoping import ScopedPathsResult

__all__ = [
    "CheckpointContext",
    "CheckpointResult",
    "ScopedPathsResult",
    "TranscriptObservability",
    "_canonical_tool_name",
    "_check_blast_radius",
    "_check_companion_drift",
    "_command_has_evidence",
    "_commit_instruction",
    "_compose_checkpoint_message",
    "_compute_log_since_window",
    "_current_branch",
    "_declare_reminder_instruction",
    "_dedupe_strings",
    "_dirty_repo_paths",
    "_extract_apply_patch_paths",
    "_extract_shell_command",
    "_git_diff_names",
    "_has_commit_evidence",
    "_has_evidence",
    "_has_evidence_after_index",
    "_is_checkpoint_project_supported",
    "_is_docs_only",
    "_is_no_action_only",
    "_iter_shell_command_records",
    "_last_scope_mutation_index",
    "_normalize_repo_path",
    "_post_commit_review_instruction",
    "_segment_matches_evidence",
    "_segment_tokens",
    "_split_shell_segments",
    "_transcript_observability",
    "build_checkpoint_message",
    "get_checkpoint_content",
    "run_heuristics",
]
