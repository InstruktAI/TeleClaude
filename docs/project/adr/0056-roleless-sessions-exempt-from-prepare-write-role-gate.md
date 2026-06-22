---
visibility: 'public'
number: '56'
date: '2026-06-22'
description: 'Prepare-artifact write authority exempts roleless (human-originated) sessions from the role allowlist and governs them by the live-holder claim; a manual lifecycle invocation on an unheld todo claims it in-process rather than spawning an orchestrator.'
---

# ADR-0056: Roleless sessions are exempt from the prepare-write role gate — ADR

## Context

Prepare-artifact writes pass through two guards in series: a role allowlist
(`refuse_non_prepare_writer`) evaluated first, then the live-holder claim
(`write_prepare_artifact_with_claim`), which claims an unheld slug for the writing
session and refuses only a _different_ live holder with HTTP 409. The role
allowlist admitted exactly two callers — a prepare-orchestrator session and a
direct human-identity session — and refused every other session by role with
HTTP 403.

A human-originated, operator-driven session carries no job role (its `job` is
unset — the `<none>` shape). Under the allowlist such a session was refused by
role before the claim guard could run, even when the slug had no live holder. The
operator could therefore neither write a prepare artifact to an unclaimed,
already-PREPARED todo nor refine it. The same role/binding premise leaked into the
lifecycle-operation door: a manual `telec todo prepare <slug>` from an unbound
operator session failed the `working_slug == slug` adoption check and fell through
to dispatching a brand-new orchestrator session, rather than claiming the unheld
todo in-process. Both behaviors contradict the claim-on-write model
(`prepare-artifact-claim-on-write`) and the audit-only stance on lineage
(`human-lineage-on-todos`): authorization derived from a role/identity premise
rather than from the live-holder claim.

## Decision

A roleless session — a TeleClaude session that carries no job role — is exempt
from the prepare-write role allowlist. Its write is governed by the live-holder
claim alone: it claims an unheld slug and is refused only as a claim conflict
against a different live holder. The role allowlist is retained for sessions that
carry an explicit non-prepare job role — a work orchestrator, a create
orchestrator, the integrator, or any worker — which remain refused by role with
HTTP 403. Prepare-orchestrator and human-identity sessions remain admitted as
before.

Symmetrically, a manual lifecycle invocation (`telec todo prepare` /
`telec todo work`) on a slug with no live holder claims the slug for the invoking
session and runs the state machine in-process; it never dispatches a separate
orchestrator session. Adoption no longer requires the invoking session to be
pre-bound to the slug.

## Consequences

- The unclaimed-refine path works: a human-originated operator session writes and
  claims an unheld prepare artifact, and a manual lifecycle invocation drives the
  todo in-process without spawning a stray orchestrator.
- The role allowlist still protects against role-bearing sessions writing prepare
  artifacts out of lane: a work orchestrator that holds the slug during the work
  phase is still refused by role, so the exemption does not widen write authority
  for any session that carries a role.
- Write authority for roleless sessions now rests entirely on the live-holder
  claim. The claim guard remains the backstop: a different live holder still
  yields HTTP 409.
- A future change that re-broadens the role allowlist to refuse roleless sessions
  would reintroduce the unclaimed-refine defect; this record is the reason the
  exemption exists.

## Alternatives Considered

- **Remove the role allowlist entirely, leaving the live-holder claim as the sole
  authority.** Rejected: during the work phase the work orchestrator is itself the
  live holder, so the claim guard alone would admit its writes to prepare
  artifacts — the out-of-lane write the role allowlist exists to refuse. Exempting
  only roleless sessions keeps that protection while fixing the human-originated
  case.
- **Set the operator session's `working_slug` to the target before adoption so the
  existing binding check passes.** Rejected: it mutates session-registry state as a
  side effect of a read-shaped invocation and couples the claim decision to a
  naming convention rather than to the live-holder signal; relaxing the binding for
  an unheld slug is the narrower change.
