---
description: 'Make structural software context explicit so humans and AI reason from shared truth instead of implicit assumptions.'
domain: 'software-development'
id: 'software-development/principle/externalized-structural-context'
scope: 'global'
type: 'principle'
visibility: 'public'
---

# Externalized Structural Context — Principle

## Principle

Software work should consume explicit structural context rather than relying on
implicit assumptions, ad hoc file reads, or keyword search as the primary
understanding mechanism.

## Rationale

Humans often carry system shape implicitly: what touches what, which contracts
matter, where tests live, which boundaries are risky, and which files are likely
to move together. That implicit understanding is fragile even for humans and is
far weaker for AI agents operating over long horizons.

Externalizing structural context makes that hidden understanding concrete:

- Humans get a clearer shared map of the system instead of relying on memory.
- AI agents get bounded, factual inputs instead of falling back to grep-driven
  guesswork.
- Planning, implementation, and review all reason from the same substrate of
  structural truth.

The goal is not to replace judgment. The goal is to automate collection of
facts so humans and AI can spend their effort on interpretation, trade-offs,
and quality.

## Implications

- Structural context is a first-class SDLC input, not an optional convenience.
- Artifact production should consume explicit codebase truth where available:
  callers, consumers, contracts, tests, boundaries, documentation, freshness,
  and known blind spots.
- Automation should stop at facts, metrics, and projections. Judgment remains a
  human/agent responsibility.
- Structural context must stay fresh against the active work surface, including
  worktrees, not only canonical main.
- When structural context is partial, the system must expose that uncertainty
  explicitly instead of pretending confidence.
- Graphs, canonical stores, and role-specific views are acceptable
  implementations of this principle, but none of them are the principle itself.

## Tensions

- Building structural context systems adds real implementation cost.
- Over-automation can tempt teams to confuse facts with judgment.
- Partial structural coverage is still useful, but only when the blind spots are
  made explicit.
- Teams must resist treating search and local file reads as sufficient once
  better shared context exists.
