---
id: 'project/adr/0020-upstream-how-is-a-hypothesis-not-a-gate'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '20'
date: '2026-06-08'
adr_status: 'accepted'
description: 'Mechanism (HOW) named in upstream intent is a verifiable hypothesis the consuming author overrides against code reality, not a directive — and not something a creation-time gate rejects.'
---

# Upstream HOW Is a Hypothesis, Not a Gate — ADR

## Context

A `dep-gated-prepare-autodispatch` input prescribed the mechanism for prepare
auto-continue verbatim: *"reuse … the parent's prepare worker … via
`telec sessions send`."* The implementer adopted that mechanism literally. The
result was a self-send: in the PREPARED auto-continue, the "parent's prepare
worker" resolved to the caller itself — the very session consuming the
instruction — so the emitted command told the session to message itself
(`prepare_step_support.py::build_prepare_autocontinue`). The mechanism was wrong
because it never matched the runtime topology, and nobody checked: the input's
HOW became implementation truth without verification.

The general failure mode: upstream artifacts (`input`, `prd`, `architecture`)
are authored before the code is examined, yet downstream authors trust their
mechanism hints as decisions. No later gate catches this — a plan that adopts an
unverified mechanism passes review when the reviewer checks the same unverified
assumption. The question raised: should the platform **gate** inputs that state
HOW, or change how consumers **treat** HOW?

## Decision

Treat any mechanism named in an upstream artifact as a **verifiable hypothesis**
at the point of consumption, never a directive. The consuming author derives the
HOW from code reality; when the upstream mechanism conflicts with what the code
supports, reality wins and the divergence is recorded in the produced artifact.
A mechanism divergence is the steward's call, taken without stopping the human;
the human is surfaced only when correcting the HOW forces a scope/intent change.

We explicitly **reject a creation-time gate** that blocks or rejects inputs for
carrying HOW. The rule lives on the consumer side, codified in
`software-development/policy/preparation-artifact-quality` (the "Consuming
upstream intent — HOW is a hypothesis" rule), backed by the producer-side
input-quality rule and by `general/principle/grounding`.

## Consequences

- The leak is caught where the knowledge is — by the author standing in front of
  the code — instead of at the input boundary where it cannot be judged.
- Adopting an upstream mechanism without verifying it against the source is a
  defect even when the mechanism happens to be correct; the reviewer flags
  unverified adoption, not just wrong outcomes.
- Useful mechanism hints survive as grounding leads rather than being discarded.
- A small cost: every consumer must verify mechanism hints it might otherwise
  have taken for free, and must record divergences so the wrong guess does not
  re-propagate.

## Alternatives Considered

- **Hard creation-time gate rejecting HOW-bearing inputs.** Rejected on three
  grounds: (1) it enforces at the wrong end — the producer (a human dump or
  upstream agent) is the party least able to judge whether a mechanism is sound;
  (2) "constraint that narrows the solution space" and "leakage HOW" are
  semantically indistinguishable to code — gating them reliably would require an
  LLM judge grading free text, which `general/principle/intelligence-boundaries`
  forbids; (3) it discards mechanism hints that are valuable grounding leads even
  when wrong.
- **Per-procedure duplication of the rule.** Rejected: the consuming procedures
  (intake, architecture, plan-draft, the reviewers) all reference
  `preparation-artifact-quality`, so stating the rule once there propagates to
  every author and reviewer. Duplicating it per procedure violates the
  state-it-once discipline.
