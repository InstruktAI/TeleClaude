"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses session_scoping.resolve_scoped_paths for turn-local file attribution and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

from instrukt_ai_logging import get_logger

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
    _has_commit_evidence,
    _has_commit_evidence_after_last_mutation,
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
    _current_branch,
    _current_head_sha,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _extract_shell_touched_paths,
    _extract_turn_file_signals,
    _file_matches_category,
    _head_changed_since_anchor,
    _is_checkpoint_project_supported,
    _is_docs_only,
    _is_no_action_only,
    _looks_like_path_token,
    _normalize_repo_path,
    _scope_git_files_to_current_turn,
    _segment_tokens,
    _split_shell_segments,
    _transcript_observability,
)
from teleclaude.hooks.checkpoint._models import CheckpointContext, CheckpointResult, TranscriptObservability
from teleclaude.hooks.checkpoint_flags import has_post_commit_review_flag, replace_post_commit_review_flag
from teleclaude.session_scoping import ScopedPathsResult, resolve_scoped_paths
from teleclaude.utils.transcript import TurnTimeline, extract_effective_tool_calls

logger = get_logger(__name__)

__all__ = [
    "CheckpointContext",
    "CheckpointResult",
    "ScopedPathsResult",
    "TranscriptObservability",
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
    "_commit_instruction",
    "_compose_checkpoint_message",
    "_compute_log_since_window",
    "_current_branch",
    "_current_head_sha",
    "_dedupe_strings",
    "_enrich_error",
    "_extract_apply_patch_paths",
    "_extract_plan_file_paths",
    "_extract_shell_command",
    "_extract_shell_touched_paths",
    "_extract_turn_file_signals",
    "_file_matches_category",
    "_has_commit_evidence",
    "_has_evidence",
    "_has_evidence_after_index",
    "_has_status_evidence",
    "_head_changed_since_anchor",
    "_is_checkpoint_project_supported",
    "_is_docs_only",
    "_is_no_action_only",
    "_iter_shell_command_records",
    "_last_category_mutation_index",
    "_looks_like_path_token",
    "_normalize_repo_path",
    "_post_commit_review_instruction",
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
    git_head_changed_this_turn: bool = False,
    post_commit_review_already_seen: bool = False,
) -> CheckpointResult:
    """Run all checkpoint heuristics and return structured result."""
    result = CheckpointResult()
    result.on_main = _current_branch(context.project_path) == "main"
    result.git_head_changed_this_turn = git_head_changed_this_turn
    result.commit_action_required = not _has_commit_evidence_after_last_mutation(
        timeline,
        git_files,
        context.project_path,
    )
    if result.git_head_changed_this_turn and not git_files:
        result.commit_action_required = False

    def append_required_action(action: str) -> None:
        if action not in result.required_actions:
            result.required_actions.append(action)

    if result.on_main and result.git_head_changed_this_turn and not post_commit_review_already_seen:
        append_required_action(_post_commit_review_instruction())
        result.post_commit_review_action_required = True

    # 1. File categorization
    categories: list[FileCategory] = _categorize_files(git_files)
    result.categories = [c.name for c in categories]

    # 2. Build required actions with verification gap detection
    for category in sorted(categories, key=lambda c: c.precedence):
        if not category.instruction:
            continue  # e.g., hook runtime — no action needed

        # Main-only categories (setup, deps, daemon restart) are irrelevant in
        # worktrees — the running system is installed from main and unaffected
        # until integration. These are the integrator's responsibility.
        if category.main_only and not result.on_main:
            continue

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
        append_required_action("Run targeted tests for only YOUR changed behavior")

    # Test quality review gate: point to policy, not inline rules
    if any(c.name == "tests only" for c in categories):
        append_required_action(
            "Test files were modified — review against test policy before committing: "
            "`telec docs get software-development/policy/testing`. Remove tests that violate policy."
        )

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


def _commit_instruction(on_main: bool) -> str:
    """Branch-aware commit instruction for the checkpoint message."""
    if on_main:
        return (
            "Collect your changes (what changed, why, file types, scope) "
            "Then execute `telec code commit` (no flags) to surface Path A/B/C; "
            "after picking, re-run with `--approved '<message>'`."
        )
    return "Commit your changes with `telec code commit --approved '<message>'`"


def _post_commit_review_instruction() -> str:
    """Instruction emitted when a main-branch commit occurred in the turn."""
    return (
        "A main-branch commit occurred this turn. Surface the `telec code commit` "
        "review gate to the user with your recommendation before reporting completion."
    )


def _docs_check_instruction() -> str:
    """Instruction that documentation updates must happen before commit."""
    return "Docs check: if relevant, update existing docs or add a new doc"


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
    commit_line = _commit_instruction(result.on_main)
    commit_lines = [commit_line] if result.commit_action_required else []

    # Special case: docs only
    if (not git_files or _is_docs_only(git_files)) and not result.required_actions and not result.observations:
        body = " ".join(commit_lines)
        return (
            f"{CHECKPOINT_PREFIX}No code changes detected this turn. Did you run `telec sync`?\n"
            f"{body}\n\n{response_policy}\n\n{escape_hatch}"
        )

    # Special case: all clear
    if result.is_all_clear:
        body = " ".join(
            [
                "All expected validations were observed.",
                f"{_docs_check_instruction()}.",
                *commit_lines,
            ]
        )
        return f"{CHECKPOINT_PREFIX}{body}\n\n{response_policy}\n\n{escape_hatch}"

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
        next_index = len(result.required_actions) + 1
        lines.append(f"{next_index}. {_docs_check_instruction()}")
        next_index += 1
        if result.commit_action_required:
            lines.append(f"{next_index}. {commit_line}")
            next_index += 1
        lines.append(f"{next_index}. All steps done — only then proceed")

    # Observations (bullet points)
    if result.observations:
        lines.append("")
        lines.append("Observations:")
        for obs in result.observations:
            lines.append(f"- {obs}")

    lines.append("")
    if result.required_actions:
        lines.append("Execute every required action above before responding to the user.")
    else:
        lines.append("Review and resolve the observations before responding to the user.")
    lines.append("")
    lines.append(response_policy)
    lines.append("")
    lines.append(escape_hatch)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def get_checkpoint_content(
    session_id: str,
    transcript_path: str | None,
    agent_name: AgentName,
    project_path: str,
    native_session_id: str | None = None,
    working_slug: str | None = None,
    elapsed_since_turn_start_s: float | None = None,
    turn_anchor_sha: str | None = None,
) -> str | None:
    """Build context-aware checkpoint content for both hook and codex routes.

    Top-level entry point that orchestrates session-scoped path resolution,
    transcript extraction, and message building.

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

        timeline = extract_effective_tool_calls(
            transcript_path,
            agent_name,
            native_session_id=native_session_id,
            scope="checkpoint",
        )

        scoped_paths = resolve_scoped_paths(
            session_id=session_id,
            workspace_root=project_path,
            agent_name=agent_name.value,
            scope_mode="turn_delta",
            transcript_path=transcript_path,
            native_session_id=native_session_id,
            turn_anchor_sha=turn_anchor_sha,
        )
        effective_files = list(scoped_paths.paths)
        effective_files = _scope_git_files_to_current_turn(
            effective_files,
            timeline,
            project_path,
        )
        current_head_sha = _current_head_sha(project_path)
        normalized_anchor_sha = (turn_anchor_sha or "").strip()
        git_head_changed_this_turn = bool(
            current_head_sha and normalized_anchor_sha and current_head_sha != normalized_anchor_sha
        )
        post_commit_review_already_seen = bool(
            current_head_sha and has_post_commit_review_flag(session_id, current_head_sha)
        )
        force_main_commit_checkpoint = (
            git_head_changed_this_turn
            and _current_branch(project_path) == "main"
            and not post_commit_review_already_seen
        )

        # Intentionally no full-session fallback:
        # checkpoint attribution must stay strictly turn-local.
        used_session_fallback = False

        if not effective_files and not force_main_commit_checkpoint:
            logger.info(
                "Checkpoint payload skipped (no turn-local changes)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": 0,
                    "workspace_kind": scoped_paths.workspace_kind,
                    "strategy": scoped_paths.strategy,
                    "ledger_updated": scoped_paths.ledger_updated,
                    "categories": [],
                    "required_actions": 0,
                    "observations": 0,
                    "mode": "silent_no_changes",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "git_head_changed_this_turn": git_head_changed_this_turn,
                    "post_commit_review_already_seen": post_commit_review_already_seen,
                },
            )
            return None

        if _is_no_action_only(effective_files) and not force_main_commit_checkpoint:
            logger.info(
                "Checkpoint payload skipped (docs/no-action changes only)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": len(effective_files),
                    "workspace_kind": scoped_paths.workspace_kind,
                    "strategy": scoped_paths.strategy,
                    "ledger_updated": scoped_paths.ledger_updated,
                    "mode": "silent_docs_only",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "git_head_changed_this_turn": git_head_changed_this_turn,
                    "post_commit_review_already_seen": post_commit_review_already_seen,
                },
            )
            return None

        context = CheckpointContext(
            project_path=project_path,
            working_slug=working_slug,
            agent_name=agent_name,
        )
        log_since_window = _compute_log_since_window(elapsed_since_turn_start_s)

        result = run_heuristics(
            effective_files,
            timeline,
            context,
            log_since_window=log_since_window,
            git_head_changed_this_turn=git_head_changed_this_turn,
            post_commit_review_already_seen=post_commit_review_already_seen,
        )

        message = _compose_checkpoint_message(effective_files, result)
        if result.post_commit_review_action_required and current_head_sha:
            replace_post_commit_review_flag(session_id, current_head_sha)
        mode = (
            "main_head_changed"
            if force_main_commit_checkpoint
            else "docs_only"
            if _is_docs_only(effective_files)
            else ("all_clear" if result.is_all_clear else "actionable")
        )
        logger.info(
            "Checkpoint payload computed",
            extra={
                **base_extra,
                "timeline_has_data": timeline.has_data,
                "timeline_records": len(timeline.tool_calls),
                "changed_files": len(effective_files),
                "workspace_kind": scoped_paths.workspace_kind,
                "strategy": scoped_paths.strategy,
                "ledger_updated": scoped_paths.ledger_updated,
                "categories": result.categories,
                "required_actions": len(result.required_actions),
                "observations": len(result.observations),
                "mode": mode,
                "message_len": len(message),
                "used_session_fallback": used_session_fallback,
                "git_head_changed_this_turn": git_head_changed_this_turn,
                "post_commit_review_already_seen": post_commit_review_already_seen,
                "post_commit_review_action_required": result.post_commit_review_action_required,
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
