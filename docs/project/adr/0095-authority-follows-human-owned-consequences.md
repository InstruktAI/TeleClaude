---
visibility: internal
number: 95
date: 2026-09-20
description: Decision authority follows the material consequence a person can evaluate, while technical and process mechanisms remain agent-owned.
---

# Authority Follows Human-Owned Consequences — ADR

## Context

The prior authority contract assigned every change to validation and delivery
rules to the human and gated broadly labelled destructive, security-sensitive,
or high-cost actions on human approval. In practice that made process documents
and technical risk labels transfer decision ownership. Humans were asked to
approve hooks, validation composition, recovery paths, and other mechanisms
they neither needed nor wanted to evaluate.

That artifact-based ownership contradicted the platform's stewardship model:
agents hold the technical wheel, humans contribute intent and lived judgment,
and independent reviewers—not the human—catch technical erosion. The decision
was contestable because removing the blanket human gate could either restore
that division of responsibility or let agents weaken controls that constrain
their own work.

## Decision

Decision authority follows the underlying consequence, not the artifact or
technical domain in which it appears.

A genuine fork belongs to the human only when its alternatives materially
concern the human, their users, business, commitments, or important assets;
produce meaningfully different outcomes, commitments, or risks rather than
different mechanisms; and can be evaluated by the human at the outcome level.
The human retains intent, material experience, exclusive-domain judgment, scope,
external commitments, material risk acceptance, and their participation
contract.

Agents own technical architecture, implementation, process evolution,
validation and delivery mechanics, review composition, recovery, and routine
security or operational work. Existing independent review governs those
changes. A relaxation of a validation or delivery control requires explicit
approval from a separate reviewer with no stake in the work it would unblock;
it does not require human technical approval.

Safety authorization concerns exposure of human-owned assets or commitments to
material, hard-to-reverse consequences. It never transfers mechanism selection.

## Consequences

- Humans are no longer a generic approval service for process and technical
  mechanics.
- Agents carry greater accountability for process design and must record the
  material reason and before/after guarantee of process changes.
- Existing review lanes, reviewer separation, citations, and blocking verdict
  arithmetic remain the technical control surface; no parallel review lane is
  introduced.
- Reviewers enforce both sides of the boundary: agents may neither take a
  human-owned outcome nor hand an agent-owned mechanism to the human.
- Safety gates become narrower and more legible, but reviewers must judge
  materiality and reversibility rather than relying on labels.
- Misclassification remains possible. The remedy is independent consequence
  review and citation to the human contract, not broader human approval.

## Alternatives Considered

- **Keep every validation and delivery rule human-owned.** Rejected because it
  assigns technical process design to the participant least positioned to
  evaluate it and conflicts with stewardship.
- **Make every decision agent-owned.** Rejected because intent, commitments,
  values, material risk, and the participation contract remain irreducibly
  human.
- **Add a dedicated process-review lane.** Rejected because the existing review
  system already provides independence, complete lane coverage, and blocking
  verdict arithmetic; the missing element was authority classification, not
  another workflow.
