"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses git diff for file-based signals and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

import logging

from teleclaude.constants import (
    CHECKPOINT_LOG_CHECK_EVIDENCE,
    CHECKPOINT_MESSAGE,
    CHECKPOINT_PREFIX,
    CHECKPOINT_TEST_EVIDENCE,
    FileCategory,
)
from teleclaude.core.agents import AgentName
from teleclaude.hooks.checkpoint._evidence import (
    _check_edit_hygiene,
    _check_error_state,
    _check_slug_alignment,
    _command_has_evidence,
    _command_invokes_search,
    _command_references_file,
    _commands_overlap,
    _compute_log_since_window,
    _dedupe_strings,
    _enrich_error,
    _extract_plan_file_paths,
    _has_evidence,
    _has_evidence_after_index,
    _has_status_evidence,
    _iter_shell_command_records,
    _last_category_mutation_index,
    _segment_matches_evidence,
)
from teleclaude.hooks.checkpoint._git import (
    _canonical_tool_name,
    _categorize_files,
    _command_likely_mutates_files,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _extract_shell_touched_paths,
    _extract_turn_file_signals,
    _file_matches_category,
    _get_uncommitted_files,
    _is_checkpoint_project_supported,
    _is_docs_only,
    _looks_like_path_token,
    _normalize_repo_path,
    _scope_git_files_to_current_turn,
    _segment_tokens,
    _split_shell_segments,
    _transcript_observability,
)
from teleclaude.hooks.checkpoint._models import (
    CheckpointContext,
    CheckpointResult,
    TranscriptObservability,
)
from teleclaude.utils.transcript import TurnTimeline, extract_tool_calls_current_turn

logger = logging.getLogger(__name__)

__all__ = [
    # Public API
    "CheckpointContext",
    "CheckpointResult",
    "TranscriptObservability",
    # Re-exported internals (used by tests and hooks)
    "_canonical_tool_name",
    "_categorize_files",
    "_check_edit_hygiene",
    "_check_error_state",
    "_check_slug_alignment",
    "_command_has_evidence",
    "_command_invokes_search",
    "_command_likely_mutates_files",
    "_command_references_file",
    "_commands_overlap",
    "_compute_log_since_window",
    "_dedupe_strings",
    "_enrich_error",
    "_extract_apply_patch_paths",
    "_extract_plan_file_paths",
    "_extract_shell_command",
    "_extract_shell_touched_paths",
    "_extract_turn_file_signals",
    "_file_matches_category",
    "_get_uncommitted_files",
    "_has_evidence",
    "_has_evidence_after_index",
    "_has_status_evidence",
    "_is_checkpoint_project_supported",
    "_is_docs_only",
    "_iter_shell_command_records",
    "_last_category_mutation_index",
    "_looks_like_path_token",
    "_normalize_repo_path",
    "_scope_git_files_to_current_turn",
    "_segment_matches_evidence",
    "_segment_tokens",
    "_split_shell_segments",
    "_transcript_observability",
    "build_checkpoint_message",
    "get_checkpoint_content",
    "run_heuristics",
]


# ---------------------------------------------------------------------------
# Heuristic engine (R2-R8)
# ---------------------------------------------------------------------------


def run_heuristics(
    git_files: list[str],
    timeline: TurnTimeline,
    context: CheckpointContext,
    log_since_window: str = "2m",
) -> CheckpointResult:
    """Run all checkpoint heuristics and return structured result."""
    result = CheckpointResult()

    def append_required_action(action: str) -> None:
        if action not in result.required_actions:
            result.required_actions.append(action)

    # 1. File categorization
    categories: list[FileCategory] = _categorize_files(git_files)
    result.categories = [c.name for c in categories]

    # 2. Build required actions with verification gap detection
    for category in sorted(categories, key=lambda c: c.precedence):
        if not category.instruction:
            continue  # e.g., hook runtime — no action needed

        evidence_seen = False
        if category.evidence_substrings:
            if category.evidence_must_follow_last_mutation:
                mutation_idx = _last_category_mutation_index(timeline, category, context.project_path)
                if mutation_idx is not None:
                    evidence_seen = _has_evidence_after_index(
                        timeline,
                        category.evidence_substrings,
                        mutation_idx,
                    )
                else:
                    evidence_seen = _has_evidence(timeline, category.evidence_substrings)
            else:
                evidence_seen = _has_evidence(timeline, category.evidence_substrings)

        if category.evidence_substrings and evidence_seen:
            # Also check for status evidence when daemon/config restart was suppressed
            if "make restart" in category.instruction and not _has_status_evidence(timeline):
                append_required_action("Run `make status` to verify daemon health")
            continue  # Suppress the main instruction

        append_required_action(category.instruction)
        # Add observation about missing verification
        if timeline.has_data and category.evidence_substrings:
            result.observations.append(
                f"{category.name.capitalize()} was modified but "
                f"`{category.evidence_substrings[0]}` was not observed this turn"
            )

    # Add log check if code changed and not already done
    has_code_changes = any(c.name != "tests only" for c in categories)
    if has_code_changes and not _has_evidence(timeline, CHECKPOINT_LOG_CHECK_EVIDENCE):
        append_required_action(f"Check logs: `instrukt-ai-logs teleclaude --since {log_since_window}`")

    # Add test instruction if code changed and not already done
    if categories and not _has_evidence(timeline, CHECKPOINT_TEST_EVIDENCE):
        append_required_action("Run targeted tests for changed behavior")

    # 3. Error state detection
    result.observations.extend(_check_error_state(timeline))

    # 4. Edit hygiene
    result.observations.extend(_check_edit_hygiene(timeline, git_files))

    # 5. Working slug alignment
    result.observations.extend(_check_slug_alignment(git_files, context))

    # Keep observations signal-rich and non-repetitive.
    result.observations = _dedupe_strings(result.observations)

    # Determine all-clear
    if not result.required_actions and not result.observations:
        result.is_all_clear = True

    return result


# ---------------------------------------------------------------------------
# Message composition (R9)
# ---------------------------------------------------------------------------


def build_checkpoint_message(
    git_files: list[str],
    timeline: TurnTimeline,
    context: CheckpointContext,
    log_since_window: str = "2m",
) -> str:
    """Build a structured checkpoint message from all signal sources."""
    result = run_heuristics(git_files, timeline, context, log_since_window=log_since_window)
    return _compose_checkpoint_message(git_files, result)


def _compose_checkpoint_message(git_files: list[str], result: CheckpointResult) -> str:
    """Compose checkpoint text from precomputed heuristic output."""
    response_policy = (
        "Response policy: complete ALL required actions first. "
        "Do not compose the debrief until every action is done. "
        "Then end with a short user-relevant debrief about actual task outcome, blocker, or decision needed. "
        "Do not mention checkpoint chores."
    )
    escape_hatch = (
        "Escape hatch (last resort only, and only when there is no actionable information left): "
        'run `touch "$TMPDIR/teleclaude_checkpoint_clear"` to disable checkpoints for this session. '
        "Re-enable by removing that file."
    )

    # Special case: docs only
    if not git_files or _is_docs_only(git_files):
        return (
            f"{CHECKPOINT_PREFIX}No code changes detected this turn. Did you run `telec sync`?\n"
            f"Commit if ready.\n\n{response_policy}\n\n{escape_hatch}"
        )

    # Special case: all clear
    if result.is_all_clear:
        return (
            f"{CHECKPOINT_PREFIX}All expected validations were observed. "
            "Docs check: if relevant, update existing docs or add a new doc. "
            f"Commit if ready.\n\n{response_policy}\n\n{escape_hatch}"
        )

    lines: list[str] = [f"{CHECKPOINT_PREFIX}Context-aware checkpoint"]

    # Changed files summary grouped by category
    if result.categories:
        lines.append("")
        lines.append(f"Changed: {', '.join(result.categories)}")

    # Required actions (numbered)
    if result.required_actions:
        lines.append("")
        lines.append("Required actions (BLOCKING — do not resume user-facing work until all complete):")
        for i, action in enumerate(result.required_actions, 1):
            lines.append(f"{i}. {action}")
        lines.append(f"{len(result.required_actions) + 1}. Commit changed files")
        lines.append(f"{len(result.required_actions) + 2}. All steps done — only then proceed")

    # Observations (bullet points)
    if result.observations:
        lines.append("")
        lines.append("Observations:")
        for obs in result.observations:
            lines.append(f"- {obs}")

    # Capture reminder
    lines.append("")
    lines.append("Docs check: If relevant, update existing docs or add a new doc.")
    lines.append("")
    lines.append("Execute every required action above before responding to the user.")
    lines.append("")
    lines.append(response_policy)
    lines.append("")
    lines.append(escape_hatch)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def get_checkpoint_content(
    transcript_path: str | None,
    agent_name: AgentName,
    project_path: str,
    working_slug: str | None = None,
    elapsed_since_turn_start_s: float | None = None,
) -> str | None:
    """Build context-aware checkpoint content for both hook and codex routes.

    Top-level entry point that orchestrates git diff, transcript extraction,
    and message building.

    Returns:
    - str: checkpoint payload when agent action is required or confirmation is useful.
    - None: no turn-local code changes detected; skip checkpoint entirely.
    - CHECKPOINT_MESSAGE: fail-open fallback on internal errors.
    """
    try:
        transcript_meta = _transcript_observability(transcript_path)
        base_extra = {
            "agent": agent_name.value,
            "project_path": project_path or "",
            "working_slug": working_slug or "",
            "transcript_present": bool(transcript_path),
            "transcript_path": transcript_meta["transcript_path"],
            "transcript_exists": transcript_meta["transcript_exists"],
            "transcript_size_bytes": transcript_meta["transcript_size_bytes"],
        }
        if not _is_checkpoint_project_supported(project_path):
            logger.info(
                "Checkpoint payload skipped (project out of scope)",
                extra={**base_extra, "mode": "unsupported_project", "message_len": 0},
            )
            return None

        git_files = _get_uncommitted_files(project_path)
        if git_files is None:
            logger.warning(
                "Checkpoint payload fallback to generic message (git unavailable)",
                extra=base_extra,
            )
            return CHECKPOINT_MESSAGE  # git unavailable — fall back to generic

        if transcript_path:
            timeline = extract_tool_calls_current_turn(transcript_path, agent_name)
        else:
            timeline = TurnTimeline(tool_calls=[], has_data=False)

        effective_git_files = _scope_git_files_to_current_turn(
            git_files,
            timeline,
            project_path,
        )

        # Intentionally no full-session fallback:
        # checkpoint attribution must stay strictly turn-local.
        used_session_fallback = False

        context = CheckpointContext(
            project_path=project_path,
            working_slug=working_slug,
            agent_name=agent_name,
        )
        log_since_window = _compute_log_since_window(elapsed_since_turn_start_s)

        result = run_heuristics(effective_git_files, timeline, context, log_since_window=log_since_window)
        if not effective_git_files or _is_docs_only(effective_git_files):
            logger.info(
                "Checkpoint payload skipped (no turn-local code changes)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "dirty_files": len(git_files),
                    "changed_files": len(effective_git_files),
                    "categories": result.categories,
                    "required_actions": len(result.required_actions),
                    "observations": len(result.observations),
                    "mode": "silent_no_changes",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                },
            )
            return None

        if result.is_all_clear:
            logger.info(
                "Checkpoint payload skipped (all checks already satisfied)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "dirty_files": len(git_files),
                    "changed_files": len(effective_git_files),
                    "categories": result.categories,
                    "required_actions": len(result.required_actions),
                    "observations": len(result.observations),
                    "mode": "silent_all_clear",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                },
            )
            return None

        message = _compose_checkpoint_message(effective_git_files, result)
        mode = (
            "docs_only"
            if (not effective_git_files or _is_docs_only(effective_git_files))
            else ("all_clear" if result.is_all_clear else "actionable")
        )
        logger.info(
            "Checkpoint payload computed",
            extra={
                **base_extra,
                "timeline_has_data": timeline.has_data,
                "timeline_records": len(timeline.tool_calls),
                "dirty_files": len(git_files),
                "changed_files": len(effective_git_files),
                "categories": result.categories,
                "required_actions": len(result.required_actions),
                "observations": len(result.observations),
                "mode": mode,
                "message_len": len(message),
                "used_session_fallback": used_session_fallback,
            },
        )
        return message

    except Exception:
        logger.warning(
            "Checkpoint content build failed (fail-open)",
            extra={
                "agent": agent_name.value,
                "project_path": project_path or "",
                "working_slug": working_slug or "",
                "transcript_present": bool(transcript_path),
                "transcript_path": transcript_path or "",
            },
            exc_info=True,
        )
        return CHECKPOINT_MESSAGE
