"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses session_scoping.resolve_scoped_paths for turn-local file attribution and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

from collections.abc import Callable
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import resolve_project_capability_state
from teleclaude.checkpoint_model import (
    checkpoint_model_from_project_config,
    load_checkpoint_model,
    scopes_for_action,
    triggered_action_ids,
)
from teleclaude.constants import (
    CheckpointAction,
    CheckpointModel,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.injected_text import checkpoint_text
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
    _has_review_dispatch_evidence,
    _iter_shell_command_records,
    _last_scope_mutation_index,
    _segment_matches_evidence,
)
from teleclaude.hooks.checkpoint._git import (
    WorktreeStatus,
    _canonical_tool_name,
    _command_likely_mutates_files,
    _current_branch,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _extract_shell_touched_paths,
    _extract_turn_file_signals,
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
    _worktree_status,
)
from teleclaude.hooks.checkpoint._models import (
    CheckpointActionDecision,
    CheckpointActionOutcome,
    CheckpointActionReason,
    CheckpointContext,
    CheckpointOwedAction,
    CheckpointResult,
    TranscriptObservability,
)
from teleclaude.hooks.checkpoint_flags import (
    consume_authored_main_commit_flag,
    consume_integrator_maintenance_marker,
    discharge_commit_obligation,
    discharge_integrator_maintenance_action,
    has_authored_main_commit_flag,
    read_commit_obligations,
    read_integrator_maintenance_marker,
)
from teleclaude.session_scoping import ScopedPathsResult, resolve_scoped_paths
from teleclaude.utils.transcript import TurnTimeline, extract_effective_tool_calls

logger = get_logger(__name__)

_INTEGRATOR_MAINTENANCE_ACTION_LINE = "{index}. {action}"
_INTEGRATOR_MAINTENANCE_ACTIONS_LABEL = "Outstanding actions: {actions}"
_INTEGRATOR_MAINTENANCE_LOG_WINDOW = "2m"

__all__ = [
    "CheckpointContext",
    "CheckpointResult",
    "ScopedPathsResult",
    "TranscriptObservability",
    "_canonical_tool_name",
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
    "_git_diff_names",
    "_has_commit_evidence",
    "_has_evidence",
    "_has_evidence_after_index",
    "_is_checkpoint_project_supported",
    "_is_docs_only",
    "_is_no_action_only",
    "_iter_shell_command_records",
    "_last_scope_mutation_index",
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
    model: CheckpointModel | None = None,
) -> CheckpointResult:
    """Run all checkpoint heuristics and return structured result."""
    if model is None:
        model = load_checkpoint_model(context.project_path)

    result = CheckpointResult()
    result.on_main = _current_branch(context.project_path) == "main"
    result.authored_main_commit = authored_main_commit
    # ADR-0070: a positively clean tree means there is nothing to commit.
    if _worktree_status(context.project_path) is WorktreeStatus.CLEAN:
        result.commit_action_required = False
    else:
        result.commit_action_required = bool(git_files) and not _has_commit_evidence_after_last_mutation(
            timeline,
            git_files,
            context.project_path,
        )

    def append_required_action(action: str) -> None:
        if action not in result.required_actions:
            result.required_actions.append(action)

    # The post-commit review obligation waits for a clean turn: pending file
    # changes surface the commit action first, and the authored marker remains
    # armed until the review gate is surfaced or dispatched.
    if (
        result.on_main
        and result.authored_main_commit
        and not result.commit_action_required
        and not _has_review_dispatch_evidence(timeline)
    ):
        append_required_action(_post_commit_review_instruction())
        result.post_commit_review_action_required = True

    # 1. Owed action ids: every action any changed file triggers under the merged
    # model, unioned with outstanding commit obligations (which surface only on main).
    actions_by_id = model.actions
    obligation_ids = set(commit_obligations or []) if result.on_main else set[str]()
    owed_ids = triggered_action_ids(git_files, model) | obligation_ids

    # 2. Resolve every known owed action exactly once. The registry owns both
    # main-branch maintenance and turn-local off-main eligibility; the latter
    # must not leak live-runtime checks into a worktree that cannot prove them.
    owed_actions = sorted(
        (CheckpointOwedAction(action_id=action_id) for action_id in owed_ids if action_id in actions_by_id),
        key=lambda owed_action: (actions_by_id[owed_action.action_id].precedence, owed_action.action_id),
    )
    result.owed_actions = tuple(owed_actions)
    logger.info(
        "checkpoint_action_owed",
        receiver_ingress_id=context.receiver_ingress_id,
        session_id=context.session_id,
        on_main=result.on_main,
        working_slug=context.working_slug or "",
        action_ids=[owed_action.action_id for owed_action in owed_actions],
    )

    branch_eligible_ids = sorted(
        (
            owed_action.action_id
            for owed_action in owed_actions
            if result.on_main
            or (
                not actions_by_id[owed_action.action_id].main_only
                and actions_by_id[owed_action.action_id].off_main_eligible
            )
        ),
        key=lambda aid: (actions_by_id[aid].precedence, aid),
    )
    decisions: list[CheckpointActionDecision] = []
    branch_eligible_set = set(branch_eligible_ids)
    for owed_action in owed_actions:
        action_id = owed_action.action_id
        action = actions_by_id[action_id]
        if action_id not in branch_eligible_set:
            decisions.append(
                CheckpointActionDecision(
                    action_id=action_id,
                    outcome=CheckpointActionOutcome.DEFERRED,
                    reason=CheckpointActionReason.OFF_MAIN_INELIGIBLE,
                )
            )
            continue
        if _action_has_evidence(timeline, action, model, context.project_path):
            if action_id in obligation_ids and discharge_obligation is not None:
                discharge_obligation(action_id)
            decisions.append(
                CheckpointActionDecision(
                    action_id=action_id,
                    outcome=CheckpointActionOutcome.SATISFIED,
                    reason=CheckpointActionReason.EVIDENCE_OBSERVED,
                )
            )
            continue
        append_required_action(_surface_run(action, log_since_window))
        decisions.append(
            CheckpointActionDecision(
                action_id=action_id,
                outcome=CheckpointActionOutcome.SURFACED,
                reason=CheckpointActionReason.ACTION_REQUIRED,
            )
        )

    result.action_decisions = tuple(decisions)
    logger.info(
        "checkpoint_action_decision",
        receiver_ingress_id=context.receiver_ingress_id,
        session_id=context.session_id,
        on_main=result.on_main,
        working_slug=context.working_slug or "",
        decisions=[
            {
                "action_id": decision.action_id,
                "outcome": decision.outcome,
                "reason": decision.reason,
            }
            for decision in decisions
        ],
    )

    result.categories = list(branch_eligible_ids)

    # 3. Blast-radius observation
    result.observations.extend(_check_blast_radius(git_files))
    for action_str in _check_companion_drift(git_files, context.project_path):
        append_required_action(action_str)

    # 4. Working slug alignment
    result.observations.extend(_check_slug_alignment(git_files, context))

    # Keep observations signal-rich and non-repetitive.
    result.observations = _dedupe_strings(result.observations)

    # Determine all-clear
    if not result.required_actions and not result.observations:
        result.is_all_clear = True

    return result


def _surface_run(action: CheckpointAction, log_since_window: str) -> str:
    """Render an action's surfaced instruction, filling the {window} placeholder."""
    return action.run.replace("{window}", log_since_window)


def _action_has_evidence(
    timeline: TurnTimeline,
    action: CheckpointAction,
    model: CheckpointModel,
    project_path: str,
) -> bool:
    """Return True when this cycle's evidence proves the action ran."""
    evidence = list(action.effective_evidence())
    if not evidence:
        return False
    if action.evidence_must_follow_last_mutation:
        scopes = scopes_for_action(model, action.id)
        mutation_idx = _last_scope_mutation_index(timeline, scopes, project_path)
        if mutation_idx is not None:
            return _has_evidence_after_index(timeline, evidence, mutation_idx)
    return _has_evidence(timeline, evidence)


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
) -> str | None:
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
        "A session-authored main-branch code commit is eligible for post-commit review. "
        "Dispatch the commit(s) to independent review yourself and wait for REVIEW COMPLETE "
        "before reporting completion. A REQUEST CHANGES verdict remains with this session "
        "for evidence-based rejection or in-scope remediation and re-review; carry only a "
        "genuine human-owned decision, unresolved contract deadlock, or safety gate to the human."
    )


def _compose_checkpoint_message(git_files: list[str], result: CheckpointResult) -> str | None:
    """Compose checkpoint text, or silence when there is nothing to enforce."""
    commit_line = _commit_instruction(result.on_main)
    commit_lines = [commit_line] if result.commit_action_required else []

    # Special case: docs only (bare *.md/txt/rst with no category and no pending actions)
    if (not git_files or _is_docs_only(git_files)) and not result.required_actions and not result.observations:
        if not commit_lines:
            return None
        body = " ".join(commit_lines)
        return checkpoint_text(f"No code changes detected this turn.\n{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}")

    # Special case: all clear
    if result.is_all_clear:
        body = " ".join(
            [
                "All expected validations were observed.",
                *commit_lines,
            ]
        )
        return checkpoint_text(f"{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}")

    lines: list[str] = ["Context-aware checkpoint"]

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
    if not actions:
        lines.append("Review and resolve the observations before responding to the user.")
        lines.append("")
    lines.append(_RESPONSE_POLICY)
    lines.append("")
    lines.append(_ESCAPE_HATCH)

    return checkpoint_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Integrator maintenance path
# ---------------------------------------------------------------------------


def _build_integrator_maintenance_checkpoint(
    action_ids: list[str],
    model: CheckpointModel,
) -> str | None:
    """Build a maintenance checkpoint message from outstanding action ids.

    Surfaces only main_only maintenance actions. No review, commit reminder,
    test, or log-check actions appear here.
    """
    # Integrator maintenance surfaces only main_only actions (install, deps,
    # restart, sync). Non-main_only actions are not the integrator's
    # responsibility and must not appear here regardless of the marker.
    maintenance_actions = [
        model.actions[action_id]
        for action_id in action_ids
        if action_id in model.actions and model.actions[action_id].main_only
    ]
    if not maintenance_actions:
        return None

    category_names = [action.id for action in sorted(maintenance_actions, key=lambda a: (a.precedence, a.id))]
    lines: list[str] = [
        "Integrator post-merge maintenance",
        "",
        _INTEGRATOR_MAINTENANCE_ACTIONS_LABEL.format(actions=", ".join(category_names)),
        "",
        "Required actions (maintenance after delivery — complete before next integration):",
    ]
    for i, action in enumerate(sorted(maintenance_actions, key=lambda a: (a.precedence, a.id)), 1):
        lines.append(
            _INTEGRATOR_MAINTENANCE_ACTION_LINE.format(
                index=i,
                action=_surface_run(action, _INTEGRATOR_MAINTENANCE_LOG_WINDOW),
            )
        )
    lines.extend(
        [
            "",
            _RESPONSE_POLICY,
            "",
            _ESCAPE_HATCH,
        ]
    )
    return checkpoint_text("\n".join(lines))


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
    receiver_ingress_id: str = "",
) -> str | None:
    """Build context-aware checkpoint content for both hook and codex routes.

    Top-level entry point that orchestrates session-scoped path resolution,
    transcript extraction, and message building.

    Returns:
    - str: checkpoint payload when agent action is required or confirmation is useful.
    - None: no turn-local code changes detected; skip checkpoint entirely.
    - paired checkpoint envelope: fail-open fallback on internal errors.
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
        capability_state = resolve_project_capability_state(Path(project_path).expanduser().resolve())
        checkpoint_config = capability_state.config.checkpoint if capability_state.config is not None else None
        if not _is_checkpoint_project_supported(project_path, capability_state.capabilities, checkpoint_config):
            logger.info(
                "Checkpoint payload skipped (project out of scope)",
                extra={**base_extra, "mode": "unsupported_project", "message_len": 0},
            )
            return None

        model = checkpoint_model_from_project_config(
            project_path,
            capability_state.config,
            capability_state.capabilities,
        )

        timeline = extract_effective_tool_calls(
            transcript_path,
            agent_name,
            native_session_id=native_session_id,
            scope="checkpoint",
        )

        # Integrator maintenance force-fire: when role=integrator and the checkout
        # marker is present, surface its outstanding main_only actions. Suppress
        # review/commit/test/log.
        if system_role == "integrator":
            marker = read_integrator_maintenance_marker(project_path)
            if marker is not None:
                outstanding_actions = [
                    model.actions[action_id]
                    for action_id in marker.outstanding_action_ids
                    if action_id in model.actions and model.actions[action_id].main_only
                ]
                action_ids: list[str] = []
                for action in outstanding_actions:
                    if _action_has_evidence(timeline, action, model, project_path):
                        discharge_integrator_maintenance_action(project_path, action.id)
                    else:
                        action_ids.append(action.id)
                if not action_ids:
                    consume_integrator_maintenance_marker(project_path)
                maintenance_message = _build_integrator_maintenance_checkpoint(action_ids, model)
                if maintenance_message:
                    logger.info(
                        "Checkpoint payload computed (integrator maintenance force-fire)",
                        extra={
                            **base_extra,
                            "mode": "integrator_maintenance",
                            "actions": len(action_ids),
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
            return checkpoint_text()
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
            _is_no_action_only(effective_files, model)
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
            session_id=session_id,
            receiver_ingress_id=receiver_ingress_id,
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
            model=model,
        )

        if (
            result.is_all_clear
            and not result.commit_action_required
            and not force_main_commit_checkpoint
            and (not effective_files or _is_docs_only(effective_files))
        ):
            logger.info(
                "Checkpoint payload skipped (doc/no-action turn fully satisfied)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": len(effective_files),
                    "workspace_kind": scoped_paths.workspace_kind,
                    "strategy": scoped_paths.strategy,
                    "ledger_updated": scoped_paths.ledger_updated,
                    "categories": result.categories,
                    "required_actions": 0,
                    "observations": 0,
                    "mode": "silent_docs_satisfied",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "authored_main_commit": authored_main_commit,
                },
            )
            return None

        message = _compose_checkpoint_message(effective_files, result)
        # Consume the authored-commit flag once the review obligation is surfaced
        # or discharged by a review dispatch in this cycle. If composition is
        # silent, consume before returning so a dispatched review settles the marker.
        if result.post_commit_review_action_required or _has_review_dispatch_evidence(timeline):
            consume_authored_main_commit_flag(session_id)
        if message is None:
            logger.info(
                "Checkpoint payload skipped (nothing to enforce)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": len(effective_files),
                    "workspace_kind": scoped_paths.workspace_kind,
                    "strategy": scoped_paths.strategy,
                    "ledger_updated": scoped_paths.ledger_updated,
                    "categories": result.categories,
                    "required_actions": 0,
                    "observations": 0,
                    "mode": "silent_nothing_to_enforce",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                    "authored_main_commit": authored_main_commit,
                    "post_commit_review_action_required": result.post_commit_review_action_required,
                },
            )
            return None
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
        return checkpoint_text()
