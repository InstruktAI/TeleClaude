//! Lifecycle state machine — pure transition function used by the
//! workflow service to validate phase advancement.
//!
//! Ports v1's `apply_authoritative_signal` / `adopt_prepare_handoff_phase`
//! (in `teleclaude/core/next_machine/lifecycle.py`) to a stateless
//! `(current, signal) -> next` form. Where v1 derives the next phase from
//! a full `TodoState` snapshot (artifacts present, approval stamps,
//! review verdicts, drift), v2 splits that responsibility:
//!
//! * The workflow service owns the heavy "derive phase from full state"
//!   logic and the side effects that go with it.
//! * This module owns the *legal transitions* and refuses anything outside
//!   them with [`InvalidTransition`].
//!
//! Both layers must agree on the table below; the workflow service emits
//! one [`LifecycleSignal`] per authoritative event and trusts this
//! function to validate it.
//!
//! ## v2 deviations from v1
//!
//! * **No re-entry to `Draft`.** v1 derived `Draft` whenever no prepare
//!   artifact was present; v2 always starts a new todo at `PrdDrafting`
//!   (service-layer concern). `Draft` is reachable only as a starting
//!   input from migrated v1 data — there is no transition *into* it.
//! * **Stateless `Blocked` recovery.** v1 re-derived the prior phase from
//!   the full `TodoState`. We have no state to derive from, so there is
//!   no generic `Unblocked` signal. The single supported escape from
//!   `Blocked` is [`LifecycleSignal::AdoptPrepareHandoff`], which
//!   unconditionally returns to `Prepared`; any finer-grained recovery
//!   must be emitted by the service as an explicit phase-specific signal.

use crate::models::LifecyclePhase;

/// Authoritative signal the workflow service applies to advance a todo's
/// lifecycle pointer.
///
/// Each variant represents one causally distinct event the orchestrator
/// emits (an artifact write, an approval stamp, a build hand-off, a
/// blocker being raised). Variants are intentionally narrow: a single
/// signal advances by at most one phase, and ambiguity is resolved by the
/// `(current, signal)` pair rather than by signal payload.
///
/// The legacy v1 `Unblocked` signal is intentionally absent — see the
/// module docs for the rationale and the `AdoptPrepareHandoff` escape
/// hatch.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LifecycleSignal {
    // ---- Prepare-stage signals -------------------------------------------------
    /// Initial input artifact arrived; begin PRD drafting.
    InputArtifactWritten,
    /// PRD has been spec-reviewed and is ready for human approval.
    PrdApproved,
    /// Human approved the PRD; begin architecture drafting.
    ArchitectureDrafted,
    /// Architecture artifact reviewed (`ArchitectureDrafting` → review)
    /// or review approved (`ArchitectureReview` → test specs).
    ArchitectureApproved,
    /// Architecture step skipped for this todo (refactor/migration path).
    ArchitectureSkipped,
    /// Architecture approved; begin test-specs drafting.
    TestSpecsDrafted,
    /// Test specs reviewed (`TestSpecsDrafting` → review) or review
    /// approved (`TestSpecsReview` → implementation plan).
    TestSpecsApproved,
    /// Test-specs step skipped for this todo.
    TestSpecsSkipped,
    /// Test specs approved; begin implementation-plan drafting.
    PlanDrafted,
    /// Implementation plan reviewed (`PlanDrafting` → review) or review
    /// approved (`PlanReview` → prepared).
    PlanApproved,
    /// A blocker was raised against the todo from a non-terminal phase.
    Blocked,

    // ---- Work-stage signals ---------------------------------------------------
    /// Build has been dispatched (entry to `BuildStarted` from `Prepared`
    /// or re-entry from `ReviewChangesRequested`).
    BuildStarted,
    /// Build worker finished; awaiting code review.
    BuildComplete,
    /// Code review verdict: changes requested. Build must cycle back.
    ReviewChangesRequested,
    /// Code review verdict: approved.
    ReviewApproved,
    /// Finalize stage reached the ready-to-handoff state.
    FinalizeReady,
    /// Branch handed off / delivered; lifecycle is terminal.
    HandedOff,

    // ---- Recovery hatch -------------------------------------------------------
    /// Escape `Blocked` by re-adopting the `Prepared` pointer. v1's
    /// `adopt_prepare_handoff_phase` derives a richer answer; in the
    /// stateless v2 machine we collapse the recovery to a single, safe
    /// step and let the service emit additional signals if a different
    /// pointer is needed.
    AdoptPrepareHandoff,
}

/// Raised when [`next_lifecycle_phase`] is called with a `(current,
/// signal)` pair that is not part of the transition table.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("invalid transition: cannot apply {signal:?} from {current:?}")]
pub struct InvalidTransition {
    pub current: LifecyclePhase,
    pub signal: LifecycleSignal,
}

/// Pure transition function. Given the current lifecycle phase and an
/// authoritative signal, return the next phase, or [`InvalidTransition`]
/// if the pair is not in the table.
///
/// The function is total over `(LifecyclePhase, LifecycleSignal)`: every
/// invalid pair returns `Err(InvalidTransition)` rather than panicking.
/// The terminal phase `HandedOff` accepts no signals.
pub fn next_lifecycle_phase(
    current: LifecyclePhase,
    signal: LifecycleSignal,
) -> Result<LifecyclePhase, InvalidTransition> {
    use LifecyclePhase as P;
    use LifecycleSignal as S;

    // `Blocked` from any non-terminal, non-already-blocked phase always
    // moves to `Blocked`. Encode this first so the per-phase tables stay
    // focused on forward progress.
    if matches!(signal, S::Blocked) && !matches!(current, P::Blocked | P::HandedOff) {
        return Ok(P::Blocked);
    }

    let next = match (current, signal) {
        // ---- Prepare lane: forward progress ------------------------------------
        (P::Draft, S::InputArtifactWritten) => P::PrdDrafting,

        (P::PrdDrafting, S::PrdApproved) => P::PrdHumanApproval,

        (P::PrdHumanApproval, S::ArchitectureDrafted) => P::ArchitectureDrafting,
        (P::PrdHumanApproval, S::ArchitectureSkipped) => P::TestSpecsDrafting,

        (P::ArchitectureDrafting, S::ArchitectureApproved) => P::ArchitectureReview,
        (P::ArchitectureReview, S::ArchitectureApproved) => P::TestSpecsDrafting,
        (P::ArchitectureReview, S::TestSpecsSkipped) => P::PlanDrafting,

        (P::TestSpecsDrafting, S::TestSpecsApproved) => P::TestSpecsReview,
        (P::TestSpecsReview, S::TestSpecsApproved) => P::PlanDrafting,

        (P::PlanDrafting, S::PlanApproved) => P::PlanReview,
        (P::PlanReview, S::PlanApproved) => P::Prepared,

        // ---- Work lane: forward progress and review cycle ---------------------
        (P::Prepared, S::BuildStarted) => P::BuildStarted,
        (P::BuildStarted, S::BuildComplete) => P::BuildComplete,
        (P::BuildComplete, S::ReviewChangesRequested) => P::ReviewChangesRequested,
        (P::ReviewChangesRequested, S::BuildStarted) => P::BuildStarted,
        (P::BuildComplete, S::ReviewApproved) => P::ReviewApproved,
        (P::ReviewApproved, S::FinalizeReady) => P::FinalizeReady,
        (P::FinalizeReady, S::HandedOff) => P::HandedOff,

        // ---- Blocked recovery -------------------------------------------------
        (P::Blocked, S::AdoptPrepareHandoff) => P::Prepared,

        // Anything else is not in the table.
        _ => return Err(InvalidTransition { current, signal }),
    };

    Ok(next)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::LifecyclePhase as P;

    // ---- Prepare-lane forward transitions ---------------------------------------

    #[test]
    fn draft_advances_to_prd_drafting_on_input_artifact_written() {
        let next = next_lifecycle_phase(P::Draft, LifecycleSignal::InputArtifactWritten)
            .expect("legal transition");
        assert_eq!(next, P::PrdDrafting);
    }

    #[test]
    fn prd_drafting_advances_to_prd_human_approval_on_prd_approved() {
        let next = next_lifecycle_phase(P::PrdDrafting, LifecycleSignal::PrdApproved)
            .expect("legal transition");
        assert_eq!(next, P::PrdHumanApproval);
    }

    #[test]
    fn prd_human_approval_advances_to_architecture_drafting_on_architecture_drafted() {
        let next = next_lifecycle_phase(P::PrdHumanApproval, LifecycleSignal::ArchitectureDrafted)
            .expect("legal transition");
        assert_eq!(next, P::ArchitectureDrafting);
    }

    #[test]
    fn prd_human_approval_skips_to_test_specs_drafting_on_architecture_skipped() {
        let next = next_lifecycle_phase(P::PrdHumanApproval, LifecycleSignal::ArchitectureSkipped)
            .expect("legal transition");
        assert_eq!(next, P::TestSpecsDrafting);
    }

    #[test]
    fn architecture_drafting_advances_to_architecture_review_on_architecture_approved() {
        let next = next_lifecycle_phase(
            P::ArchitectureDrafting,
            LifecycleSignal::ArchitectureApproved,
        )
        .expect("legal transition");
        assert_eq!(next, P::ArchitectureReview);
    }

    #[test]
    fn architecture_review_advances_to_test_specs_drafting_on_architecture_approved() {
        let next =
            next_lifecycle_phase(P::ArchitectureReview, LifecycleSignal::ArchitectureApproved)
                .expect("legal transition");
        assert_eq!(next, P::TestSpecsDrafting);
    }

    #[test]
    fn architecture_review_skips_to_plan_drafting_on_test_specs_skipped() {
        let next = next_lifecycle_phase(P::ArchitectureReview, LifecycleSignal::TestSpecsSkipped)
            .expect("legal transition");
        assert_eq!(next, P::PlanDrafting);
    }

    #[test]
    fn test_specs_drafting_advances_to_test_specs_review_on_test_specs_approved() {
        let next = next_lifecycle_phase(P::TestSpecsDrafting, LifecycleSignal::TestSpecsApproved)
            .expect("legal transition");
        assert_eq!(next, P::TestSpecsReview);
    }

    #[test]
    fn test_specs_review_advances_to_plan_drafting_on_test_specs_approved() {
        let next = next_lifecycle_phase(P::TestSpecsReview, LifecycleSignal::TestSpecsApproved)
            .expect("legal transition");
        assert_eq!(next, P::PlanDrafting);
    }

    #[test]
    fn plan_drafting_advances_to_plan_review_on_plan_approved() {
        let next = next_lifecycle_phase(P::PlanDrafting, LifecycleSignal::PlanApproved)
            .expect("legal transition");
        assert_eq!(next, P::PlanReview);
    }

    #[test]
    fn plan_review_advances_to_prepared_on_plan_approved() {
        let next = next_lifecycle_phase(P::PlanReview, LifecycleSignal::PlanApproved)
            .expect("legal transition");
        assert_eq!(next, P::Prepared);
    }

    // ---- Work-lane forward transitions and review cycle ------------------------

    #[test]
    fn prepared_advances_to_build_started_on_build_started() {
        let next = next_lifecycle_phase(P::Prepared, LifecycleSignal::BuildStarted)
            .expect("legal transition");
        assert_eq!(next, P::BuildStarted);
    }

    #[test]
    fn build_started_advances_to_build_complete_on_build_complete() {
        let next = next_lifecycle_phase(P::BuildStarted, LifecycleSignal::BuildComplete)
            .expect("legal transition");
        assert_eq!(next, P::BuildComplete);
    }

    #[test]
    fn build_complete_advances_to_review_changes_requested_on_review_changes_requested() {
        let next = next_lifecycle_phase(P::BuildComplete, LifecycleSignal::ReviewChangesRequested)
            .expect("legal transition");
        assert_eq!(next, P::ReviewChangesRequested);
    }

    #[test]
    fn review_changes_requested_cycles_back_to_build_started_on_build_started() {
        let next = next_lifecycle_phase(P::ReviewChangesRequested, LifecycleSignal::BuildStarted)
            .expect("legal transition");
        assert_eq!(next, P::BuildStarted);
    }

    #[test]
    fn build_complete_advances_to_review_approved_on_review_approved() {
        let next = next_lifecycle_phase(P::BuildComplete, LifecycleSignal::ReviewApproved)
            .expect("legal transition");
        assert_eq!(next, P::ReviewApproved);
    }

    #[test]
    fn review_approved_advances_to_finalize_ready_on_finalize_ready() {
        let next = next_lifecycle_phase(P::ReviewApproved, LifecycleSignal::FinalizeReady)
            .expect("legal transition");
        assert_eq!(next, P::FinalizeReady);
    }

    #[test]
    fn finalize_ready_advances_to_handed_off_on_handed_off() {
        let next = next_lifecycle_phase(P::FinalizeReady, LifecycleSignal::HandedOff)
            .expect("legal transition");
        assert_eq!(next, P::HandedOff);
    }

    // ---- Block / recover -------------------------------------------------------

    #[test]
    fn prepared_transitions_to_blocked_on_blocked_signal() {
        let next =
            next_lifecycle_phase(P::Prepared, LifecycleSignal::Blocked).expect("legal transition");
        assert_eq!(next, P::Blocked);
    }

    #[test]
    fn blocked_recovers_to_prepared_on_adopt_prepare_handoff() {
        let next = next_lifecycle_phase(P::Blocked, LifecycleSignal::AdoptPrepareHandoff)
            .expect("legal transition");
        assert_eq!(next, P::Prepared);
    }

    // ---- Representative invalid transitions ------------------------------------

    #[test]
    fn prd_approved_from_prepared_is_invalid() {
        let err = next_lifecycle_phase(P::Prepared, LifecycleSignal::PrdApproved)
            .expect_err("not in transition table");
        assert_eq!(
            err,
            InvalidTransition {
                current: P::Prepared,
                signal: LifecycleSignal::PrdApproved,
            }
        );
    }

    #[test]
    fn build_started_from_handed_off_is_invalid() {
        let err = next_lifecycle_phase(P::HandedOff, LifecycleSignal::BuildStarted)
            .expect_err("HandedOff is terminal");
        assert_eq!(
            err,
            InvalidTransition {
                current: P::HandedOff,
                signal: LifecycleSignal::BuildStarted,
            }
        );
    }

    #[test]
    fn review_approved_from_draft_is_invalid() {
        let err = next_lifecycle_phase(P::Draft, LifecycleSignal::ReviewApproved)
            .expect_err("Draft cannot jump to work lane");
        assert_eq!(
            err,
            InvalidTransition {
                current: P::Draft,
                signal: LifecycleSignal::ReviewApproved,
            }
        );
    }

    #[test]
    fn handed_off_rejects_every_signal() {
        // Exhaustive over every signal variant — HandedOff is terminal.
        let signals = [
            LifecycleSignal::InputArtifactWritten,
            LifecycleSignal::PrdApproved,
            LifecycleSignal::ArchitectureDrafted,
            LifecycleSignal::ArchitectureApproved,
            LifecycleSignal::ArchitectureSkipped,
            LifecycleSignal::TestSpecsDrafted,
            LifecycleSignal::TestSpecsApproved,
            LifecycleSignal::TestSpecsSkipped,
            LifecycleSignal::PlanDrafted,
            LifecycleSignal::PlanApproved,
            LifecycleSignal::Blocked,
            LifecycleSignal::BuildStarted,
            LifecycleSignal::BuildComplete,
            LifecycleSignal::ReviewChangesRequested,
            LifecycleSignal::ReviewApproved,
            LifecycleSignal::FinalizeReady,
            LifecycleSignal::HandedOff,
            LifecycleSignal::AdoptPrepareHandoff,
        ];
        for signal in signals {
            let err = next_lifecycle_phase(P::HandedOff, signal)
                .expect_err("HandedOff must reject every signal");
            assert_eq!(err.current, P::HandedOff);
            assert_eq!(err.signal, signal);
        }
    }
}
