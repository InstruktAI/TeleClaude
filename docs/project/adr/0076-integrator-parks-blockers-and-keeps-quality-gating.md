---
visibility: public
number: 0076
date: 2026-08-17
description: The integrator parks undeliverable candidates while retaining the complete deterministic pre-push quality gate as a blocker.
---

# Integrator Parks Blockers and Keeps Quality Gating — ADR

## Context

ADR-0065 combined park-and-drain with a quality-gate override, drain-end batch
testing, and baseline probes. That package was decided while the repository
still carried a test suite and flaky tests could wedge integration. The project
subsequently retired that suite under its test moratorium. The integration
tripwire now consists of deterministic lint, type checking, and guardrails and
is the only mechanical quality gate over the merged candidate on
`origin/main`.

The throughput problem remains: one candidate whose textual conflict, foreign
work, or gate failure cannot be grounded must not freeze unrelated deliveries.
The gate-relaxation premise does not remain: bypassing the only deterministic
merged-state check would remove protection without the batch-test and baseline
probe mechanisms that originally compensated for it.

## Decision

The integrator retains dependency-safe park-and-drain while keeping the full
pre-push quality gate authoritative and blocking.

- A candidate with an unresolvable textual conflict is parked together with
  its transitive dependents, and the drain continues through independent work.
- A candidate whose commit span is mechanically proven to carry another live
  slug's work is parked. Ambiguous provenance is surfaced to the integrator for
  judgment and never classified automatically.
- A pre-push gate failure is resolved in the integration worktree and re-pushed
  when the integrator can ground the correction. When it cannot, the candidate
  is parked and the drain continues. No candidate is delivered past a failed
  lint, type-check, or guardrail result, and no sentinel bypass exists.
- The v1 integrator adds no train-level batch test or baseline probe. Runtime
  verification follows the repository's test-moratorium contract.
- The integrator's authority still ends at the push. Post-push work confirms,
  records, and cleans up; it does not judge content.

## Consequences

- A problematic candidate no longer monopolizes a busy delivery queue.
- Every commit reaching `origin/main` still passes the deterministic merged-state
  quality gate.
- Candidate cleanliness and ungroundable gate failures gain the same loud,
  dependency-safe parking behavior as textual conflicts.
- Quality findings cannot be deferred through an integration-only override;
  they are fixed before delivery or the candidate is parked.
- The batch-verification and baseline-probe portions of ADR-0065 do not apply to
  the v1 runtime while the test moratorium stands.

## Alternatives Considered

- **Integrity-only gating with a SHA-scoped quality override.** Rejected because
  the override weakens the sole deterministic merged-state gate after its
  compensating verification mechanisms became unavailable.
- **Halt the drain on every ungroundable failure.** Rejected because independent
  candidates do not inherit the blocked candidate's uncertainty and should
  continue delivering.
