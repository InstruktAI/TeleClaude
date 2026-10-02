"""Push-rejection recovery — shared re-push-and-reclassify re-entry.

Owns the ``PUSH_REJECTED`` and ``CONTENT_GATE_BLOCKED`` re-entry steps and the
re-push-and-reclassify body they share: retry the push, and route a fresh
content-gate rejection to the beacon instruction while a fast-forward race
falls back to the ordinary rebase loop.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from instrukt_ai_logging import get_logger

from teleclaude.core.integration.candidate_scan import CandidateKey
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _get_candidate_key,
    _write_checkpoint,
)
from teleclaude.core.integration.formatters import _format_error, _format_push_rejected
from teleclaude.core.integration.git_ops import (
    _get_head_sha,
    _get_remote_main_sha,
    _integration_worktree_path,
    _run_git,
)
from teleclaude.core.integration.lifecycle_events import _emit_lifecycle_event, _workflow_subject_for_path
from teleclaude.core.integration.park import (
    _UNGROUNDABLE_CONTENT_GATE_PARK_REASON,
    _format_content_gate_conflict_or_invariant_error,
    _park_candidate,
)
from teleclaude.git_lock import main_branch_lock

logger = get_logger(__name__)

_NEXT_INTEGRATE_PHASE_LOG = "NEXT_INTEGRATE_PHASE"
_CONTENT_GATE_MARKER = "Integration push blocked"


def _is_content_gate_rejection(rejection_reason: str) -> bool:
    """Classify a push rejection as content-gate (vs. fast-forward race).

    The pre-push hook (``.githooks/pre-push``, ``trees/_integration`` branch)
    prints this stable marker when ``telec code lint --all`` fails on the
    squash content. That failure is invariant under rebase — a fast-forward
    race is the only other rejection cause and is rebase-recoverable.
    """
    return _CONTENT_GATE_MARKER in rejection_reason


class _RepushOutcome(NamedTuple):
    """Result of a shared re-push-and-reclassify attempt.

    ``resolved`` holds the ``(keep_going, instruction)`` tuple to return
    verbatim when the push landed (``PUSH_SUCCEEDED``) or the rejection was a
    content-gate block (``CONTENT_GATE_BLOCKED``). It is ``None`` when the
    rejection was a non-content-gate (fast-forward race) cause the caller must
    classify itself; ``rejection`` then carries the reason text and ``wt`` the
    resolved worktree path for the caller's fallback instruction.
    """

    resolved: tuple[bool, str] | None
    rejection: str
    wt: str


def _repush_and_reclassify(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
    key: CandidateKey,
) -> _RepushOutcome:
    """Re-attempt the push and reclassify the fresh rejection cause.

    Shared re-entry body for ``PUSH_REJECTED`` and ``CONTENT_GATE_BLOCKED``. If
    local HEAD already matches remote main, or the fresh push now lands,
    transitions to ``PUSH_SUCCEEDED`` and returns a keep-going result. On a
    content-gate rejection, transitions to ``CONTENT_GATE_BLOCKED``, emits the
    blocked beacon event, and returns the conflict instruction. On a
    non-content-gate rejection, stamps the reason into ``error_context`` and
    returns it unresolved so the caller classifies the phase itself.
    """
    wt = str(_integration_worktree_path(cwd))
    local_head = _get_head_sha(wt)
    remote_head = _get_remote_main_sha(wt)
    if local_head and remote_head and local_head == remote_head:
        checkpoint.pushed_sha = local_head
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event(
            "integration.push.succeeded",
            {"slug": key.slug, "commit_sha": local_head},
            _workflow_subject_for_path(cwd),
        )
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED (recovered)", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return _RepushOutcome((True, ""), "", wt)  # loop into PUSH_SUCCEEDED

    with main_branch_lock():
        rc, stdout, stderr = _run_git(["push", "origin", "HEAD:main"], cwd=wt)
    if rc == 0:
        checkpoint.pushed_sha = local_head
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event(
            "integration.push.succeeded",
            {"slug": key.slug, "commit_sha": local_head or "unknown"},
            _workflow_subject_for_path(cwd),
        )
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED (recovered)", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return _RepushOutcome((True, ""), "", wt)  # loop into PUSH_SUCCEEDED

    rejection = (stderr or stdout).strip()
    _emit_lifecycle_event(
        "integration.push.rejected",
        {"slug": key.slug, "rejection_reason": rejection},
        _workflow_subject_for_path(cwd),
    )

    if _is_content_gate_rejection(rejection):
        checkpoint.phase = IntegrationPhase.CONTENT_GATE_BLOCKED.value
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
        _write_checkpoint(checkpoint_path, checkpoint)
        _emit_lifecycle_event(
            "integration.candidate.blocked",
            {"slug": key.slug, "branch": key.branch, "sha": key.sha, "reason": rejection},
            _workflow_subject_for_path(cwd),
        )
        logger.info("%s slug=%s phase=CONTENT_GATE_BLOCKED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return _RepushOutcome(
            (
                False,
                _format_content_gate_conflict_or_invariant_error(
                    slug=key.slug,
                    branch=key.branch,
                    rejection_reason=rejection,
                    worktree=wt,
                    pre_merge_head=checkpoint.pre_merge_head,
                ),
            ),
            rejection,
            wt,
        )

    checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
    return _RepushOutcome(None, rejection, wt)


def _step_push_rejected(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """PUSH_REJECTED: re-attempt the push and reclassify the fresh rejection cause.

    Pushing (once the agent's out-of-band fetch/rebase is done) is mechanical, so
    the state machine performs it itself on every re-entry rather than trusting
    the checkpoint's stale ``rejection_reason``. This is what lets a
    rebase-then-re-push that now fails the content gate be observed and routed
    to ``CONTENT_GATE_BLOCKED`` — without it, that case would silently keep
    reissuing the stale race-recovery message forever (the freeze the diagnosis
    names). If local HEAD already matches remote main (the agent's own push
    already landed), no redundant push is attempted.
    """
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_REJECTED phase has no candidate key")

    outcome = _repush_and_reclassify(checkpoint=checkpoint, checkpoint_path=checkpoint_path, cwd=cwd, key=key)
    if outcome.resolved is not None:
        return outcome.resolved

    _write_checkpoint(checkpoint_path, checkpoint)
    return False, _format_push_rejected(outcome.rejection or "unknown rejection", key.slug, outcome.wt)


def _step_content_gate_blocked(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
    abandon: bool = False,
) -> tuple[bool, str]:
    """CONTENT_GATE_BLOCKED: integrator-owned logical merge conflict, re-entered.

    A groundable rejection retains ``_step_push_rejected``'s re-push-and-reclassify
    shape: the conflict instruction is re-issued as a beacon on a repeat content-gate
    failure, and recovery hands off to the ordinary PUSH_REJECTED rebase loop on a
    fast-forward race. An ungroundable rejection is abandoned when the integrator
    passes ``abandon=True``: the machine itself resets the integration worktree to
    the checkpoint-frozen ``pre_merge_head`` — discarding a commit is prohibited on
    the agent's own git surface, so the machine performs it here through the
    module's existing git execution path — and parks through the shared
    ``_park_candidate`` transition so the drain continues with the next independent
    candidate. The ``head_sha == pre_merge`` branch below is a belt-and-braces
    detector for a worktree already at the abandon target; it is not the only route.
    """
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "CONTENT_GATE_BLOCKED phase has no candidate key")

    wt = str(_integration_worktree_path(cwd))
    head_sha = _get_head_sha(wt)
    pre_merge = checkpoint.pre_merge_head
    if head_sha is None or pre_merge is None:
        return False, _format_error(
            "INVALID_STATE",
            f"CONTENT_GATE_BLOCKED phase for {key.slug} cannot read HEAD or pre_merge_head",
        )
    if head_sha == pre_merge:
        return _park_candidate(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            key=key,
            reason=_UNGROUNDABLE_CONTENT_GATE_PARK_REASON,
            subject=_workflow_subject_for_path(cwd),
        )

    if abandon:
        rc, _, stderr = _run_git(["reset", "--hard", pre_merge], cwd=wt)
        if rc != 0:
            return False, _format_error(
                "ABANDON_RESET_FAILED",
                f"CONTENT_GATE_BLOCKED phase for {key.slug} failed to reset integration "
                f"worktree to {pre_merge}: {stderr.strip()}",
            )
        return _park_candidate(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            key=key,
            reason=_UNGROUNDABLE_CONTENT_GATE_PARK_REASON,
            subject=_workflow_subject_for_path(cwd),
        )

    outcome = _repush_and_reclassify(checkpoint=checkpoint, checkpoint_path=checkpoint_path, cwd=cwd, key=key)
    if outcome.resolved is not None:
        return outcome.resolved

    checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
    _write_checkpoint(checkpoint_path, checkpoint)
    logger.info("%s slug=%s phase=PUSH_REJECTED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
    return False, _format_push_rejected(outcome.rejection or "unknown rejection", key.slug, outcome.wt)


__all__ = [
    "_is_content_gate_rejection",
    "_step_content_gate_blocked",
    "_step_push_rejected",
]
