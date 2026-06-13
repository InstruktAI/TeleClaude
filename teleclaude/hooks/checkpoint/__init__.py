"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses session_scoping.resolve_scoped_paths for turn-local file attribution and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

from collections.abc import Callable

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    CHECKPOINT_FILE_CATEGORIES,
    CHECKPOINT_LOG_CHECK_EVIDENCE,
    CHECKPOINT_MESSAGE,
    CHECKPOINT_PREFIX,
    CHECKPOINT_TEST_EVIDENCE,
    FileCategory,
)
from teleclaude.core.agents import AgentName
from teleclaude.hooks.checkpoint._evidence import (
    _check_blast_radius,
    _check_companion_drift,
    _check_slug_alignment,
    _command_has_evidence,
    _compute_log_since_window,
    _dedupe_strings,
    _extract_plan_file_paths,
    _has_commit_evidence,
    _has_commit_evidence_after_last_mutation,
    _has_evidence,
    _has_evidence_after_index,
    _iter_shell_command_records,
    _last_category_mutation_index,
    _segment_matches_evidence,
)
from teleclaude.hooks.checkpoint._git import (
    _canonical_tool_name,
    _categorize_files,
    _command_likely_mutates_files,
    _current_branch,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _extract_shell_touched_paths,
    _extract_turn_file_signals,
    _file_matches_category,
    _git_diff_names,
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
from teleclaude.hooks.checkpoint_flags import (
    consume_authored_main_commit_flag,
    consume_integrator_maintenance_marker,
    discharge_commit_obligation,
    has_authored_main_commit_flag,
    read_commit_obligations,
    read_integrator_maintenance_marker,
)
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
    "_check_blast_radius",
    "_check_companion_drift",
    "_check_slug_alignment",
    "_command_has_evidence",
    "_command_likely_mutates_files",
    "_commit_instruction",
    "_compose_checkpoint_message",
    "_compute_log_since_window",
    "_current_branch",
    "_dedupe_strings",
    "_extract_apply_patch_paths",
    "_extract_plan_file_paths",
    "_extract_shell_command",
    "_extract_shell_touched_paths",
    "_extract_turn_file_signals",
    "_file_matches_category",
    "_has_commit_evidence",
    "_has_evidence",
    "_has_evidence_after_index",
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
    authored_main_commit: bool = False,
    commit_obligations: list[str] | None = None,
    discharge_obligation: Callable[[str], bool] | None = None,
) -> CheckpointResult:
    """Run all checkpoint heuristics and return structured result."""
    result = CheckpointResult()
    result.on_main = _current_branch(context.project_path) == "main"
    result.authored_main_commit = authored_main_commit
    result.commit_action_required = bool(git_files) and not _has_commit_evidence_after_last_mutation(
        timeline,
        git_files,
        context.project_path,
    )

    def append_required_action(action: str) -> None:
        if action not in result.required_actions:
            result.required_actions.append(action)

    if result.on_main and result.authored_main_commit:
        append_required_action(_post_commit_review_instruction())
        result.post_commit_review_action_required = True

    # 1. File categorization and commit-obligation sourcing
    file_categories: list[FileCategory] = _categorize_files(git_files)
    obligation_categories = _commit_obligation_categories(commit_obligations or [], result.on_main)
    categories = _dedupe_categories([*file_categories, *obligation_categories])
    obligation_names = {category.name for category in obligation_categories}
    result.categories = [c.name for c in categories]

    # 2. Build required actions with verification gap detection
    for category in sorted(categories, key=lambda c: c.precedence):
        if not category.instruction:
            continue  # e.g., hook runtime — no action needed

        # Main-only categories (telec setup, dependencies, daemon code, config) are irrelevant in
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
            if category.name in obligation_names and discharge_obligation is not None:
                discharge_obligation(category.name)
            continue  # Suppress the main instruction

        append_required_action(category.instruction)
        # Add observation about missing verification
        if timeline.has_data and category.evidence_substrings:
            result.observations.append(
                f"{category.name.capitalize()} was modified but "
                f"`{category.evidence_substrings[0]}` was not observed this turn"
            )

    # Add log check if runtime code changed and not already done. Doc/artifact
    # sources (is_code=False) deploy via sync — they have no runtime to inspect.
    has_code_changes = any(c.is_code and c.name != "tests only" for c in file_categories)
    if has_code_changes and not _has_evidence(timeline, CHECKPOINT_LOG_CHECK_EVIDENCE):
        append_required_action(f"Check logs: `instrukt-ai-logs teleclaude --since {log_since_window}`")

    # Add test instruction if code changed and not already done. Doc/artifact-only
    # turns have no behavior to test.
    if any(c.is_code for c in file_categories) and not _has_evidence(timeline, CHECKPOINT_TEST_EVIDENCE):
        append_required_action("Run targeted tests for only YOUR changed behavior")

    # Test quality review gate: point to policy, not inline rules
    if any(c.name == "tests only" for c in file_categories):
        append_required_action(
            "Test files were modified — review against test policy before committing: "
            "`telec docs get software-development/policy/testing`. Remove tests that violate policy."
        )

    # 3. Blast-radius observation
    result.observations.extend(_check_blast_radius(git_files))
    for action in _check_companion_drift(git_files, context.project_path):
        append_required_action(action)

    # 5. Working slug alignment
    result.observations.extend(_check_slug_alignment(git_files, context))

    # Keep observations signal-rich and non-repetitive.
    result.observations = _dedupe_strings(result.observations)

    # Determine all-clear
    if not result.required_actions and not result.observations:
        result.is_all_clear = True

    return result


def _commit_obligation_categories(obligations: list[str], on_main: bool) -> list[FileCategory]:
    """Return checkpoint categories for outstanding commit-derived obligations."""
    if not on_main:
        return []
    obligation_names = set(obligations)
    return [
        category
        for category in CHECKPOINT_FILE_CATEGORIES
        if category.name in obligation_names and category.main_only and category.instruction
    ]


def _dedupe_categories(categories: list[FileCategory]) -> list[FileCategory]:
    """Return checkpoint categories once, preserving first-seen order."""
    seen: set[str] = set()
    deduped: list[FileCategory] = []
    for category in categories:
        if category.name in seen:
            continue
        seen.add(category.name)
        deduped.append(category)
    return deduped


# ---------------------------------------------------------------------------
# Message composition (R9)
# ---------------------------------------------------------------------------

_RESPONSE_POLICY = (
    "Response policy: complete ALL required actions first. "
    "Do not compose the debrief until every action is done. "
    "Then end with a short user-relevant debrief about actual task outcome, blocker, or decision needed. "
    "Do not mention checkpoint chores."
)
_ESCAPE_HATCH = (
    "Escape hatch (last resort only, and only when there is no actionable information left): "
    'run `touch "$TMPDIR/teleclaude_checkpoint_clear"` to skip checkpoints for this turn; '
    "it clears at the next user prompt. If the same checkpoint recurs across turns, "
    "surface it as a bug instead of clearing it again."
)


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
        return "Execute `telec code commit` (no flags) to surface the menu."
    return "Commit your changes with `telec code commit --approved '<message>'`"


def _post_commit_review_instruction() -> str:
    """Instruction emitted when a main-branch commit occurred in the turn."""
    return (
        "A main-branch commit occurred this turn. Surface the `telec code commit` "
        "review gate to the user with your recommendation before reporting completion. "
        "If you recommend review, set a non-blocking 5-minute heartbeat after that "
        "message; if the heartbeat fires without a user response approving or declining "
        "review, dispatch the commit(s) to review yourself and wait for REVIEW COMPLETE."
    )


def _compose_checkpoint_message(git_files: list[str], result: CheckpointResult) -> str:
    """Compose checkpoint text from precomputed heuristic output."""
    commit_line = _commit_instruction(result.on_main)
    commit_lines = [commit_line] if result.commit_action_required else []

    # Special case: docs only (bare *.md/txt/rst with no category and no pending actions)
    if (not git_files or _is_docs_only(git_files)) and not result.required_actions and not result.observations:
        body = " ".join(commit_lines)
        return (
            f"{CHECKPOINT_PREFIX}No code changes detected this turn.\n{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}"
        )

    # Special case: all clear
    if result.is_all_clear:
        body = " ".join(
            [
                "All expected validations were observed.",
                *commit_lines,
            ]
        )
        return f"{CHECKPOINT_PREFIX}{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}"

    lines: list[str] = [f"{CHECKPOINT_PREFIX}Context-aware checkpoint"]

    # Changed files summary grouped by category
    if result.categories:
        lines.append("")
        lines.append(f"Changed: {', '.join(result.categories)}")

    # Required actions (numbered). The commit instruction belongs to the action list
    # whenever any action applies — including a pending commit that has no other required
    # action (e.g. an uncommitted no-action turn). This guarantees an uncommitted change
    # is never silently dropped on a branch that lacks code actions.
    actions = list(result.required_actions)
    if result.required_actions or result.commit_action_required:
        if result.commit_action_required:
            actions.append(commit_line)

    if actions:
        lines.append("")
        lines.append("Required actions (BLOCKING — do not resume user-facing work until all complete):")
        for i, action in enumerate(actions, 1):
            lines.append(f"{i}. {action}")

    # Observations (bullet points)
    if result.observations:
        lines.append("")
        lines.append("Observations:")
        for obs in result.observations:
            lines.append(f"- {obs}")

    lines.append("")
    if actions:
        lines.append("Execute every required action above before responding to the user.")
    else:
        lines.append("Review and resolve the observations before responding to the user.")
    lines.append("")
    lines.append(_RESPONSE_POLICY)
    lines.append("")
    lines.append(_ESCAPE_HATCH)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integrator maintenance path
# ---------------------------------------------------------------------------


def _build_integrator_maintenance_checkpoint(
    merge_ranges: list[str],
    project_path: str,
    timeline: TurnTimeline,
) -> str | None:
    """Build a maintenance checkpoint message from merge-delta files.

    Surfaces only main_only maintenance category instructions, with evidence
    suppression. No review, commit reminder, test, or log-check actions.
    """
    all_files: list[str] = []
    for merge_range in merge_ranges:
        all_files.extend(_git_diff_names(project_path, merge_range))

    if not all_files:
        return None

    categories = _categorize_files(all_files)
    # Integrator maintenance surfaces only main_only categories (telec setup,
    # dependencies, daemon code, config, syncable sources). Non-main_only categories like agent-artifacts
    # (restart-self) are not the integrator's maintenance responsibility and must
    # not appear here regardless of what files were in the merge delta.
    maintenance_categories = [c for c in categories if c.main_only]
    if not maintenance_categories:
        return None

    actions: list[str] = []
    for category in sorted(maintenance_categories, key=lambda c: c.precedence):
        if not category.instruction:
            continue
        evidence_seen = False
        if category.evidence_substrings:
            evidence_seen = _has_evidence(timeline, category.evidence_substrings)
        if category.evidence_substrings and evidence_seen:
            continue
        actions.append(category.instruction)

    if not actions:
        return None

    category_names = [c.name for c in maintenance_categories]
    lines: list[str] = [
        f"{CHECKPOINT_PREFIX}Integrator post-merge maintenance",
        "",
        f"Changed (merge delta): {', '.join(category_names)}",
        "",
        "Required actions (maintenance after delivery — complete before next integration):",
    ]
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")
    lines.extend(
        [
            "",
            "Execute every required action above before responding to the user.",
            "",
            _RESPONSE_POLICY,
            "",
            _ESCAPE_HATCH,
        ]
    )
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
    system_role: str | None = None,
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

        # Integrator maintenance force-fire: when role=integrator and the maintenance
        # marker is present, source effective_files from the merge delta and surface
        # only main_only maintenance category instructions. Suppress review/commit/test/log.
        if system_role == "integrator":
            marker_content = read_integrator_maintenance_marker(session_id)
            if marker_content:
                merge_ranges = [r for r in marker_content.strip().splitlines() if r]
                maintenance_message = _build_integrator_maintenance_checkpoint(merge_ranges, project_path, timeline)
                if maintenance_message:
                    consume_integrator_maintenance_marker(session_id)
                    logger.info(
                        "Checkpoint payload computed (integrator maintenance force-fire)",
                        extra={
                            **base_extra,
                            "mode": "integrator_maintenance",
                            "merge_ranges": len(merge_ranges),
                            "message_len": len(maintenance_message),
                        },
                    )
                    return maintenance_message

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
        try:
            commit_obligations = read_commit_obligations(session_id)
        except OSError:
            logger.warning(
                "Commit obligations marker read failed",
                extra={**base_extra, "mode": "commit_obligations_read_failed"},
                exc_info=True,
            )
            return CHECKPOINT_MESSAGE
        authored_main_commit = has_authored_main_commit_flag(session_id)
        force_main_commit_checkpoint = authored_main_commit and _current_branch(project_path) == "main"

        # Intentionally no full-session fallback:
        # checkpoint attribution must stay strictly turn-local.
        used_session_fallback = False

        if not effective_files and not force_main_commit_checkpoint and not commit_obligations:
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
                    "authored_main_commit": authored_main_commit,
                },
            )
            return None

        docs_committed = _has_commit_evidence_after_last_mutation(
            timeline,
            effective_files,
            project_path,
        )
        if (
            _is_no_action_only(effective_files)
            and not force_main_commit_checkpoint
            and not commit_obligations
            and docs_committed
        ):
            logger.info(
                "Checkpoint payload skipped (no-action changes only, already committed)",
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
                    "authored_main_commit": authored_main_commit,
                },
            )
            return None

        context = CheckpointContext(
            project_path=project_path,
            working_slug=working_slug,
            agent_name=agent_name,
            system_role=system_role,
        )
        log_since_window = _compute_log_since_window(elapsed_since_turn_start_s)

        result = run_heuristics(
            effective_files,
            timeline,
            context,
            log_since_window=log_since_window,
            authored_main_commit=authored_main_commit,
            commit_obligations=commit_obligations,
            discharge_obligation=lambda action: discharge_commit_obligation(session_id, action),
        )

        if not effective_files and commit_obligations and result.is_all_clear and not force_main_commit_checkpoint:
            logger.info(
                "Checkpoint payload skipped (commit obligations satisfied)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": 0,
                    "workspace_kind": scoped_paths.workspace_kind,
                    "strategy": scoped_paths.strategy,
                    "ledger_updated": scoped_paths.ledger_updated,
                    "categories": result.categories,
                    "required_actions": 0,
                    "observations": 0,
                    "mode": "commit_obligations_satisfied",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "authored_main_commit": authored_main_commit,
                },
            )
            return None

        message = _compose_checkpoint_message(effective_files, result)
        if result.post_commit_review_action_required:
            consume_authored_main_commit_flag(session_id)
        mode = (
            "main_commit_authored"
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
                "authored_main_commit": authored_main_commit,
                "post_commit_review_action_required": result.post_commit_review_action_required,
            },
        )
        logger.trace(
            "Checkpoint payload content",
            extra={
                **base_extra,
                "observations": list(result.observations),
                "required_actions": list(result.required_actions),
                "categories": result.categories,
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
