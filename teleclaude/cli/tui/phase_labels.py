"""Enum-to-label mapping for prepare and integration phase display in TodoRow."""

from __future__ import annotations

_PREPARE_LABELS: dict[str, tuple[str, str]] = {
    "input_assessment": ("P:discovery", "cyan"),
    "triangulation": ("P:discovery", "cyan"),
    "requirements_review": ("P:requirements", "cyan"),
    "plan_drafting": ("P:planning", "cyan"),
    "plan_review": ("P:planning", "cyan"),
    "gate": ("P:planning", "cyan"),
    "grounding_check": ("P:planning", "cyan"),
    "re_grounding": ("P:planning", "cyan"),
    "blocked": ("P:blocked", "red"),
}

_INTEGRATION_STARTED: frozenset[str] = frozenset(
    {
        "candidate_dequeued",
        "clearance_wait",
        "merge_clean",
        "merge_conflicted",
        "awaiting_commit",
        "committed",
        "delivery_bookkeeping",
    }
)

_INTEGRATION_DELIVERED: frozenset[str] = frozenset({"push_succeeded", "cleanup", "candidate_delivered", "completed"})


def prepare_phase_label(phase: str | None) -> tuple[str, str] | None:
    """Map a prepare phase value to a (display_label, color) tuple.

    Returns None for terminal/absent phases (prepared, empty, unknown).
    """
    if not phase:
        return None
    return _PREPARE_LABELS.get(phase)


def integration_phase_label(
    phase: str | None,
    finalize_status: str | None,
) -> tuple[str, str] | None:
    """Map an integration phase + finalize_status to a (display_label, color) tuple.

    Returns None when no integration activity is present.
    """
    if phase:
        if phase in _INTEGRATION_STARTED:
            return ("I:started", "magenta")
        if phase in _INTEGRATION_DELIVERED:
            return ("I:delivered", "green")
        if phase == "push_rejected":
            return ("I:failed", "red")
        return None

    # No active integration phase — check queued handoff signal
    if finalize_status == "handed_off":
        return ("I:queued", "magenta")

    return None
