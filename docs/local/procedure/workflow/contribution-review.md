---
description: Assess an unprepared proposal from trusted upstream context and retain its evidence for ordinary preparation.
visibility: internal
delivered_by:
  - reviewed-pr-contributions
role: work-orchestrator
parameters:
  - name: adoption_id
    required: true
dispatch:
  agent:
    - codex
    - claude
  thinking_mode: slow
---

# Contribution Review — Procedure

## Required reads

@~/.teleclaude/docs/sdlc/procedure/lifecycle/review.md
@docs/local/spec/feature/workflow/contribution-adoption.md

## Goal

Produce the upstream assessment of the pinned proposal and its prior evidence.
The proposal is the review subject; the upstream assignment supplies the
governing context.

## Preconditions

- The dispatch identifies the adoption record and retained proposal revision.
- The proposal has no prepared upstream owning item; prepared owning work uses
  its ordinary work driver as first reviewer.
- The session starts with upstream-owned instructions and configuration.
- The contribution inspection surface exposes the proposed source, contracts
  and report identities.

## Steps

1. Read the identified contribution and its versioned prior reports through
   the contribution inspection surface. Establish the intended outcome and
   current upstream contracts independently before reconciling prior claims.
2. Assess the pinned source and reports under the shared review contract.
   Examine setup, hooks, dependencies, workflows and imported instructions as
   review material. Keep inspection read-only until the admission decision.
3. Record which obligations the evidence satisfies, unresolved findings,
   preparation gaps, whether executable preparation may proceed and which
   native checks remain owed. Submit the complete assessment through the
   contribution operation against the assigned adoption identity.
4. Record the declared admission result through the contribution review
   operation, binding the report digest and proposal revision. A changed
   subject returns for assessment under the contribution-adoption contract.
5. Return the assessment in this session's output. The intake operation retains
   source and evidence, settles this reviewer-only assignment, and completes
   the ordinary-item handoff. The ordinary preparation/work owner
   consumes the assessment as evidence under the contribution-adoption
   contract. This assignment performs no item phase, claim or readiness act.

## Outputs

- A versioned review report covering corroborated evidence, findings,
  preparation gaps, execution readiness and outstanding native checks.
- A revision-bound admission result recorded through workflow's contribution
  operation.
- A retained-source handoff to the ordinary upstream item lifecycle.

## Recovery

An unavailable subject or unresolved preparation gap is reported with its
evidence. Retain the imported proposal and existing findings for the owning
orchestrator's next contribution (`general/procedure/orchestration`).
