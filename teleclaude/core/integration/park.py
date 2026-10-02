"""Candidate parking — the shared park transition for undeliverable candidates.

Owns every closed park reason token and the one transition every park path
routes through.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.integration.candidate_scan import CandidateKey
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    ParkedCandidate,
    _now_iso,
    _reset_candidate,
    _write_checkpoint,
)
from teleclaude.core.integration.formatters import _format_content_gate_conflict, _format_error
from teleclaude.core.integration.lifecycle_events import _EVENT_INTEGRATION_CANDIDATE_PARKED, _emit_lifecycle_event
from teleclaude.events.envelope import EventSubject

logger = get_logger(__name__)

_TEXTUAL_CONFLICT_PARK_REASON = "unresolvable textual merge conflict"
_UNGROUNDABLE_CONTENT_GATE_PARK_REASON = "ungroundable_content_gate"


def _park_candidate(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    key: CandidateKey,
    reason: str,
    subject: EventSubject,
) -> tuple[bool, str]:
    """Park a candidate for the current drain and reset to IDLE for the next dequeue.

    Shared transition for every park path — textual conflict and
    ungroundable content-gate rejection: appends the
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
    _emit_lifecycle_event(_EVENT_INTEGRATION_CANDIDATE_PARKED, dict(parked), subject)
    _reset_candidate(checkpoint)
    _write_checkpoint(checkpoint_path, checkpoint)
    return True, ""


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
    "_TEXTUAL_CONFLICT_PARK_REASON",
    "_UNGROUNDABLE_CONTENT_GATE_PARK_REASON",
    "_format_content_gate_conflict_or_invariant_error",
    "_park_candidate",
]
