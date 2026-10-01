"""Resolve a stop's changed files into the checkpoint result.

Owed actions and their decisions, commit and post-commit review obligations,
and blast-radius and companion observations.
"""

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import load_checkpoint_model, scopes_for_action, triggered_action_ids
from teleclaude.constants import CheckpointAction, CheckpointModel
from teleclaude.hooks.checkpoint._directives import _surface_run
from teleclaude.hooks.checkpoint._evidence import (
    _check_blast_radius,
    _check_companion_drift,
    _dedupe_strings,
    _has_commit_evidence_after_last_mutation,
    _has_evidence,
    _has_evidence_after_index,
    _has_review_dispatch_evidence,
    _last_scope_mutation_index,
)
from teleclaude.hooks.checkpoint._git import WorktreeStatus, _current_branch, _worktree_status
from teleclaude.hooks.checkpoint._integrator import _defers_to_integrator
from teleclaude.hooks.checkpoint._models import (
    CheckpointActionDecision,
    CheckpointActionOutcome,
    CheckpointActionReason,
    CheckpointContext,
    CheckpointOwedAction,
    CheckpointResult,
)
from teleclaude.utils.transcript import TurnTimeline

__all__ = ["_post_commit_review_instruction", "run_heuristics"]

logger = get_logger("teleclaude.hooks.checkpoint")  # Preserve the package's record identity.


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
        if _defers_to_integrator(action, context.system_role):
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


def _post_commit_review_instruction() -> str:
    """Instruction emitted when a main-branch commit occurred in the turn."""
    return (
        "A session-authored main-branch code commit is eligible for post-commit review. "
        "Dispatch the commit(s) to independent review yourself and wait for REVIEW COMPLETE "
        "before reporting completion. A REQUEST CHANGES verdict remains with this session "
        "for evidence-based rejection or in-scope remediation and re-review. What you and the "
        "reviewer cannot resolve, you hold: go idle with it and route it nowhere "
        "(general/principle/autonomy)."
    )
