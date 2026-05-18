---
description: 'How code intelligence feeds SDLC stages as structural input for planning, execution, review, and concurrent integration.'
domain: 'software-development'
id: 'software-development/design/code-intelligence-sdlc-integration'
scope: 'global'
type: 'design'
visibility: 'public'
---

# Code Intelligence SDLC Integration — Design

## Required reads

- @~/.teleclaude/docs/software-development/design/code-intelligence.md
- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define where code intelligence is consumed inside the SDLC and what role it
plays at each stage.

The goal is not to reshape the lifecycle around code intelligence. The goal is
to make structural context an explicit input wherever it raises judgment
quality.

## Inputs/Outputs

**Inputs**

- canonical code-intelligence facts and metrics
- role-specific views
- freshness, provenance, and blind-spot signals

**Outputs**

- better-informed SDLC judgments
- more explicit impact, scope, and overlap awareness
- reduced dependence on grep-driven discovery and guesswork

## Invariants

- Code intelligence is an SDLC input substrate, not a lifecycle phase.
- SDLC stages remain responsible for their own judgments, approvals, and
  artifact authority.
- Structural context should be consumed where it materially improves quality,
  not added performatively to every step.
- A degraded or partial code-intelligence result must change consumer behavior
  explicitly rather than being ignored.

## Primary flows

### Prepare consumption

Prepare can consume code intelligence when shaping scope, impact, and execution
planning.

High-value uses:

- identifying touched boundaries, callers, consumers, contracts, and adjacent
  tests
- surfacing documentation obligations and blind spots
- giving planners a structural change surface before they decompose execution

The prepare phase still owns the resulting artifacts. Code intelligence only
improves the quality of the supporting evidence.

### Work consumption

Work can consume code intelligence during build and review.

High-value uses:

- helping builders see relevant structural adjacency before they change code
- helping reviewers compare intended scope with actual changed surfaces
- highlighting drift, blind spots, or surprising impact patterns

The work loop still decides whether a change is acceptable. Code intelligence
sharpens the evidence available to that loop.

### Integration consumption

Integration can consume code intelligence to improve concurrency management.

High-value uses:

- structural overlap awareness between queued deliveries
- dependency and cutover-risk signals
- identifying when independent branch-local validity is still unsafe at the
  system level

Integration still owns sequencing and landing judgment. Code intelligence helps
make those judgments less accidental and less dependent on manual grep-style
inspection.

### Degradation behavior

When code intelligence is partial or unsupported:

- the consuming SDLC stage must see that explicitly
- targeted investigation must replace blind trust in the result
- the lifecycle must degrade to more manual judgment, not to false certainty

## Failure modes

- SDLC stages treat code intelligence as authoritative judgment instead of
  supporting evidence
- degraded or partial views are consumed as if they were complete
- consumers ignore structural context and fall back to ad hoc discovery even
  when better inputs exist
- the integration pipeline remains blind to concurrency overlap even after
  structural input exists

## See Also

- ~/.teleclaude/docs/software-development/design/sdlc/prepare.md —
  prepare-phase artifact production and rigor model
- ~/.teleclaude/docs/software-development/design/sdlc/work.md —
  work-phase build/review/fix loops
- ~/.teleclaude/docs/software-development/design/sdlc/integration.md —
  concurrency-aware landing and sequencing
