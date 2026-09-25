"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses session_scoping.resolve_workspace and the durable declaration record for
turn-local file attribution, and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

from datetime import UTC, datetime
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
    LOG_CHECK_ACTION_ID,
    CheckpointAction,
    CheckpointModel,
    JudgmentOwner,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.injected_text import checkpoint_text
from teleclaude.hooks.checkpoint._evidence import (
    _check_blast_radius,
    _check_companion_drift,
    _command_has_evidence,
    _compute_log_since_window,
    _dedupe_strings,
    _has_commit_evidence,
    _has_commit_evidence_after_last_mutation,
    _has_evidence,
    _has_evidence_after_index,
    _has_post_ready_log_check_evidence,
    _has_review_dispatch_evidence,
    _integrator_judgment_log_window,
    _iter_shell_command_records,
    _last_scope_mutation_index,
    _segment_matches_evidence,
)
from teleclaude.hooks.checkpoint._git import (
    WorktreeStatus,
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
    has_authored_main_commit_flag,
)
from teleclaude.hooks.integrator_judgment_marker import (
    discharge_integrator_judgment,
    read_integrator_judgment_marker,
)
from teleclaude.project_root import declaration_root
from teleclaude.session_scoping import ScopedPathsResult, WorkspaceKind, live_declarations, resolve_workspace
from teleclaude.utils.transcript import TurnTimeline, extract_effective_tool_calls

logger = get_logger(__name__)

_INTEGRATOR_MAINTENANCE_ACTION_LINE = "{index}. {action}"
_INTEGRATOR_MAINTENANCE_ACTIONS_LABEL = "Outstanding actions: {actions}"
_INTEGRATOR_LOG_JUDGMENT_TITLE = "Integrator post-merge log judgment"
_INTEGRATOR_LOG_JUDGMENT_REQUIRED_ACTIONS = (
    "Required actions (log judgment after delivery — complete before next integration):"
)
_CHECKPOINT_BUILD_FAILED_MESSAGE = "Checkpoint content build failed; no checkpoint emitted"
_INTEGRATOR_ROLE = "integrator"
_INTEGRATOR_JUDGMENT_NOT_READY_EVENT = "integrator_judgment_not_ready"
_INTEGRATOR_JUDGMENT_FORCE_FIRE_EVENT = "Checkpoint payload computed (integrator maintenance force-fire)"
_INTEGRATOR_LOG_JUDGMENT_MODE = "integrator_log_judgment"

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


# ---------------------------------------------------------------------------
# Heuristic engine (R2-R8)
# ---------------------------------------------------------------------------


def run_heuristics(
    git_files: list[str],
    timeline: TurnTimeline,
    context: CheckpointContext,
    log_since_window: str = "2m",
    authored_main_commit: bool = False,
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

    # 1. Owed action ids: every changed file triggers judgment actions under the
    # merged checkpoint registry. Deterministic maintenance completed at the
    # commit boundary belongs only to the maintenance registry.
    actions_by_id = model.actions
    owed_ids = triggered_action_ids(git_files, model)

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
    integrator_owned_ids: set[str] = set()
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
        if action.judged_by is JudgmentOwner.INTEGRATOR and context.system_role != _INTEGRATOR_ROLE:
            integrator_owned_ids.add(action_id)
            decisions.append(
                CheckpointActionDecision(
                    action_id=action_id,
                    outcome=CheckpointActionOutcome.DEFERRED,
                    reason=CheckpointActionReason.INTEGRATOR_OWNED,
                )
            )
            continue
        if _action_has_evidence(timeline, action, model, context.project_path):
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

    result.categories = [action_id for action_id in branch_eligible_ids if action_id not in integrator_owned_ids]

    # 3. Blast-radius observation
    result.observations.extend(_check_blast_radius(git_files))
    for action_str in _check_companion_drift(git_files, context.project_path):
        append_required_action(action_str)

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


def _declare_reminder_instruction() -> str:
    """Reminder emitted beside a commit action, for any file not yet declared."""
    return "Declare any file you changed that isn't declared yet: `telec code add <path>...`"


def _compose_checkpoint_message(git_files: list[str], result: CheckpointResult) -> str | None:
    """Compose checkpoint text, or silence when there is nothing to enforce."""
    commit_line = _commit_instruction(result.on_main)
    commit_lines = [commit_line, _declare_reminder_instruction()] if result.commit_action_required else []

    # Special case: docs only (bare *.md/txt/rst with no category and no pending actions)
    if (not git_files or _is_docs_only(git_files)) and not result.required_actions and not result.observations:
        if not commit_lines:
            return None
        body = " ".join(commit_lines)
        return checkpoint_text(f"No code changes detected this turn.\n{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}")

    # Special case: all clear
    if result.is_all_clear:
        if not result.commit_action_required:
            return None
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
            actions.append(_declare_reminder_instruction())

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


def _build_integrator_log_judgment_checkpoint(
    action_ids: list[str],
    model: CheckpointModel,
    window: str,
) -> str | None:
    """Build a checkpoint message from outstanding post-merge log actions.

    Surfaces only main-only judgment actions recorded by integration. No review,
    commit reminder, test, or maintenance action appears here.
    """
    judgment_actions = [
        model.actions[action_id]
        for action_id in action_ids
        if action_id in model.actions and model.actions[action_id].main_only
    ]
    if not judgment_actions:
        return None

    category_names = [action.id for action in sorted(judgment_actions, key=lambda a: (a.precedence, a.id))]
    lines: list[str] = [
        _INTEGRATOR_LOG_JUDGMENT_TITLE,
        "",
        _INTEGRATOR_MAINTENANCE_ACTIONS_LABEL.format(actions=", ".join(category_names)),
        "",
        _INTEGRATOR_LOG_JUDGMENT_REQUIRED_ACTIONS,
    ]
    for i, action in enumerate(sorted(judgment_actions, key=lambda a: (a.precedence, a.id)), 1):
        lines.append(
            _INTEGRATOR_MAINTENANCE_ACTION_LINE.format(
                index=i,
                action=_surface_run(action, window),
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
    system_role: str | None = None,
    receiver_ingress_id: str = "",
) -> str | None:
    """Build context-aware checkpoint content for both hook and codex routes.

    Top-level entry point that orchestrates session-scoped path resolution,
    transcript extraction, and message building.

    Returns:
    - str: checkpoint payload when maintenance work is established.
    - None: no checkpoint work is established or evaluation fails.
    """
    try:
        transcript_meta = _transcript_observability(transcript_path)
        base_extra = {
            "agent": agent_name.value,
            "receiver_ingress_id": receiver_ingress_id,
            "session_id": session_id,
            "project_path": project_path or "",
            "working_slug": working_slug or "",
            "transcript_present": bool(transcript_path),
            "transcript_path": transcript_meta["transcript_path"],
            "transcript_exists": transcript_meta["transcript_exists"],
            "transcript_size_bytes": transcript_meta["transcript_size_bytes"],
        }
        capability_state = resolve_project_capability_state(declaration_root(Path(project_path).expanduser().resolve()))
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

        if system_role == _INTEGRATOR_ROLE:
            marker = read_integrator_judgment_marker(project_path)
            if marker is not None and marker.ready_at is None:
                logger.info(
                    _INTEGRATOR_JUDGMENT_NOT_READY_EVENT,
                    activation_ids=[activation.after_sha for activation in marker.activations],
                )
            elif marker is not None:
                action_ids = [
                    action_id
                    for action_id in marker.action_ids
                    if action_id == LOG_CHECK_ACTION_ID and action_id in model.actions
                ]
                if action_ids:
                    action = model.actions[LOG_CHECK_ACTION_ID]
                    earliest_activation = min(
                        marker.activations,
                        key=lambda activation: activation.activated_at,
                    ).activated_at
                    if _has_post_ready_log_check_evidence(
                        timeline,
                        action.effective_evidence(),
                        earliest_activation,
                        marker.ready_at,
                    ):
                        discharge_integrator_judgment(project_path, marker)
                    else:
                        window = _integrator_judgment_log_window(earliest_activation, datetime.now(UTC))
                        log_judgment_message = _build_integrator_log_judgment_checkpoint(
                            action_ids,
                            model,
                            window,
                        )
                        if log_judgment_message:
                            logger.info(
                                _INTEGRATOR_JUDGMENT_FORCE_FIRE_EVENT,
                                receiver_ingress_id=receiver_ingress_id,
                                session_id=session_id,
                                project_path=project_path,
                                mode=_INTEGRATOR_LOG_JUDGMENT_MODE,
                                actions=len(action_ids),
                                message_len=len(log_judgment_message),
                            )
                            return log_judgment_message

        workspace = resolve_workspace(project_path)
        declared_paths = {declaration.path for declaration in live_declarations(session_id)}
        # Declarations answer ownership only where sessions share a branch. A
        # worktree is one todo's task scope with a single writer, so its
        # obligation is the dirty tree itself; intersecting it with declarations
        # would withhold the obligation from the session that owns every path
        # in it.
        dirty_paths = _dirty_repo_paths(project_path)
        if workspace.kind is WorkspaceKind.GIT_WORKTREE:
            effective_files = sorted(dirty_paths)
        else:
            effective_files = sorted(declared_paths & dirty_paths)
        authored_main_commit = has_authored_main_commit_flag(session_id)
        force_main_commit_checkpoint = authored_main_commit and _current_branch(project_path) == "main"
        used_session_fallback = False

        if not effective_files and not force_main_commit_checkpoint:
            logger.info(
                "Checkpoint payload skipped (no declared-and-dirty changes)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": 0,
                    "workspace_kind": workspace.kind,
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
        if _is_no_action_only(effective_files, model) and not force_main_commit_checkpoint and docs_committed:
            logger.info(
                "Checkpoint payload skipped (no-action changes only, already committed)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "changed_files": len(effective_files),
                    "workspace_kind": workspace.kind,
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
                    "workspace_kind": workspace.kind,
                    "categories": result.categories,
                    "commit_action_required": result.commit_action_required,
                    "docs_only": _is_docs_only(effective_files),
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
                    "workspace_kind": workspace.kind,
                    "categories": result.categories,
                    "commit_action_required": result.commit_action_required,
                    "docs_only": _is_docs_only(effective_files),
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
                "workspace_kind": workspace.kind,
                "categories": result.categories,
                "commit_action_required": result.commit_action_required,
                "docs_only": _is_docs_only(effective_files),
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
            _CHECKPOINT_BUILD_FAILED_MESSAGE,
            extra={
                "agent": agent_name.value,
                "project_path": project_path or "",
                "working_slug": working_slug or "",
                "transcript_present": bool(transcript_path),
                "transcript_path": transcript_path or "",
            },
            exc_info=True,
        )
        return None
