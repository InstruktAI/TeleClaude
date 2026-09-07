"""Candidate parking — the shared park transition and span-ownership ambiguity.

Owns every closed park reason token, the one transition every park path
routes through, the observation log for a mechanical cleanliness decision,
and the ambiguity evidence carried through checkpoint ``error_context``
between a squash decision and its re-entry.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.core.integration.candidate_scan import AmbiguityEvidence, CandidateCleanlinessResult, CandidateKey
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    ParkedCandidate,
    _now_iso,
    _reset_candidate,
    _write_checkpoint,
)
from teleclaude.core.integration.formatters import _format_content_gate_conflict, _format_error
from teleclaude.core.integration.lifecycle_events import _EVENT_INTEGRATION_CANDIDATE_PARKED, _emit_lifecycle_event

logger = get_logger(__name__)

_TEXTUAL_CONFLICT_PARK_REASON = "unresolvable textual merge conflict"
_CANDIDATE_CLEANLINESS_PARK_REASON = "candidate_cleanliness"
_UNGROUNDABLE_CONTENT_GATE_PARK_REASON = "ungroundable_content_gate"
_CANDIDATE_CLEANLINESS_DECIDED_LOG = "integration_candidate_cleanliness_decided"
_ERROR_CONTEXT_AMBIGUITY_FIELD = "ambiguity"


def _park_candidate(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    key: CandidateKey,
    reason: str,
) -> tuple[bool, str]:
    """Park a candidate for the current drain and reset to IDLE for the next dequeue.

    Shared transition for every park path — textual conflict, candidate
    cleanliness, and ungroundable content-gate rejection: appends the
    structured parked record, increments ``items_blocked``, emits
    ``integration.candidate.parked``, applies the candidate reset, persists,
    and returns the loop-and-continue result every caller re-enters IDLE with.
    """
    parked = ParkedCandidate(
        slug=key.slug,
        branch=key.branch,
        sha=key.sha,
        reason=reason,
        parked_at=_now_iso(),
    )
    checkpoint.parked.append(parked)
    checkpoint.items_blocked += 1
    _emit_lifecycle_event(_EVENT_INTEGRATION_CANDIDATE_PARKED, dict(parked))
    _reset_candidate(checkpoint)
    _write_checkpoint(checkpoint_path, checkpoint)
    return True, ""


def _log_candidate_cleanliness_decision(key: CandidateKey, cleanliness: CandidateCleanlinessResult) -> None:
    """Emit the stable INFO observation record for a cleanliness inspection.

    No subject text or payload body — only identifiers and the closed outcome
    and reason-token vocabulary.
    """
    logger.info(
        _CANDIDATE_CLEANLINESS_DECIDED_LOG,
        extra={
            "slug": key.slug,
            "candidate_sha": key.sha,
            "outcome": cleanliness.outcome.value,
            "reason_token": cleanliness.evidence.reason_token if cleanliness.evidence else "",
            "evidence_commit_sha": cleanliness.evidence.commit_sha if cleanliness.evidence else "",
        },
    )


# guard: loose-dict-func - checkpoint error_context is a per-phase metadata bag (shape varies by phase)
def _error_context_with_ambiguity(base: dict[str, Any], ambiguity: AmbiguityEvidence | None) -> dict[str, Any]:
    """Merge span-ownership ambiguity evidence into a per-phase error_context payload."""
    if ambiguity is None:
        return base
    return {
        **base,
        _ERROR_CONTEXT_AMBIGUITY_FIELD: {"commit_sha": ambiguity.commit_sha, "reason_token": ambiguity.reason_token},
    }


# guard: loose-dict-func - checkpoint error_context is a per-phase metadata bag (shape varies by phase)
def _ambiguity_from_error_context(error_context: dict[str, Any] | None) -> AmbiguityEvidence | None:
    """Reconstruct span-ownership ambiguity evidence persisted in checkpoint.error_context, if any."""
    if not error_context:
        return None
    raw = error_context.get(_ERROR_CONTEXT_AMBIGUITY_FIELD)
    if not isinstance(raw, dict):
        return None
    commit_sha = raw.get("commit_sha")
    reason_token = raw.get("reason_token")
    if not isinstance(commit_sha, str) or not isinstance(reason_token, str):
        return None
    return AmbiguityEvidence(commit_sha=commit_sha, reason_token=reason_token)


def _format_content_gate_conflict_or_invariant_error(
    *, slug: str, branch: str, rejection_reason: str, worktree: str, pre_merge_head: str | None
) -> str:
    """Render the content-gate conflict, or a named invariant error if pre_merge_head is unrecorded.

    The ungroundable-abandon action renders a literal reset target; rendering
    a placeholder or resetting against ``origin/main`` instead of the frozen
    pre-merge SHA would silently discard more than the rejected squash.
    """
    if not pre_merge_head:
        return _format_error(
            "INVALID_STATE",
            f"CONTENT_GATE_BLOCKED phase for {slug} has no recorded pre_merge_head to abandon to",
        )
    return _format_content_gate_conflict(slug, branch, rejection_reason, worktree, pre_merge_head)


__all__ = [
    "_CANDIDATE_CLEANLINESS_PARK_REASON",
    "_TEXTUAL_CONFLICT_PARK_REASON",
    "_UNGROUNDABLE_CONTENT_GATE_PARK_REASON",
    "_ambiguity_from_error_context",
    "_error_context_with_ambiguity",
    "_format_content_gate_conflict_or_invariant_error",
    "_log_candidate_cleanliness_decision",
    "_park_candidate",
]
