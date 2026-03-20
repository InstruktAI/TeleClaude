"""Work lifecycle machine definition — states, transitions, and shared mappings.

Provides the canonical machine for the full todo lifecycle (prepare + work phases).
Used by mark-* wrappers, the API route, and display layers.
"""

from __future__ import annotations

from teleclaude.core.next_machine.state_machine import StateMachine, TransitionDefinition

# ── Ordered lifecycle states ──────────────────────────────────────────────────
# Covers both prepare and work phases. Order determines idempotency:
# if current is past the target, the transition is a no-op.
LIFECYCLE_STATES: list[str] = [
    # Prepare phases
    "input_assessment",
    "triangulation",
    "requirements_review",
    "test_spec_build",
    "test_spec_review",
    "plan_drafting",
    "plan_review",
    "gate",
    "grounding_check",
    "re_grounding",
    "prepared",
    # Work phases
    "build_started",
    "build_complete",
    "review_pending",
    "review_changes_requested",
    "review_approved",
    "finalize_ready",
    "finalize_handed_off",
]

# ── Canonical current → (build_status, review_status) mapping ─────────────────
# Single source of truth for deriving legacy build/review status pairs from the
# v2 current value. Used by work.py dispatch and roadmap.py display.
CURRENT_TO_BUILD_REVIEW: dict[str, tuple[str, str]] = {
    "prepared": ("pending", "pending"),
    "build_started": ("started", "pending"),
    "build_complete": ("complete", "pending"),
    "review_pending": ("complete", "pending"),
    "review_changes_requested": ("started", "changes_requested"),
    "review_approved": ("complete", "approved"),
    "finalize_ready": ("complete", "approved"),
    "finalize_handed_off": ("complete", "approved"),
}

# ── Transition definitions ────────────────────────────────────────────────────
_TRANSITIONS: list[TransitionDefinition] = [
    # Prepare phase transitions (for CLI/API firing)
    TransitionDefinition(
        name="approve_requirements",
        sources={"requirements_review"},
        target="test_spec_build",
    ),
    TransitionDefinition(
        name="approve_test_specs",
        sources={"test_spec_review"},
        target="plan_drafting",
    ),
    TransitionDefinition(
        name="approve_plan",
        sources={"plan_review"},
        target="gate",
    ),
    TransitionDefinition(
        name="pass_gate",
        sources={"gate"},
        target="grounding_check",
    ),
    TransitionDefinition(
        name="mark_prepared",
        sources={"grounding_check", "re_grounding"},
        target="prepared",
    ),
    # Work phase transitions
    TransitionDefinition(
        name="start_build",
        sources={"prepared", "review_changes_requested", "build_complete"},
        target="build_started",
    ),
    TransitionDefinition(
        name="complete_build",
        sources={"build_started"},
        target="build_complete",
    ),
    TransitionDefinition(
        name="request_review",
        sources={"build_complete"},
        target="review_pending",
    ),
    TransitionDefinition(
        name="approve_review",
        sources={"review_pending"},
        target="review_approved",
    ),
    TransitionDefinition(
        name="request_changes",
        sources={"review_pending"},
        target="review_changes_requested",
    ),
    TransitionDefinition(
        name="mark_finalize_ready",
        sources={"review_approved"},
        target="finalize_ready",
    ),
    TransitionDefinition(
        name="finalize_handoff",
        sources={"finalize_ready"},
        target="finalize_handed_off",
    ),
]


def build_lifecycle_machine() -> StateMachine:
    """Return the canonical work lifecycle state machine."""
    return StateMachine(states=LIFECYCLE_STATES, transitions=_TRANSITIONS)


# ── mark_phase → transition mapping ──────────────────────────────────────────
# Maps (phase, status) pairs from the legacy mark_phase API to transition names.
MARK_PHASE_TO_TRANSITION: dict[tuple[str, str], str] = {
    ("build", "started"): "start_build",
    ("build", "complete"): "complete_build",
    ("review", "pending"): "request_review",
    ("review", "approved"): "approve_review",
    ("review", "changes_requested"): "request_changes",
}
