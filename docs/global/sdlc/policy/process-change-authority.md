---
description: Process evolution is agent-owned and doc-first, governed by existing independent review, with human authority determined only by the underlying consequence.
---

# Process Change Authority — Policy

## Rules

### The process layer is its doc contract

The process layer governs how software work is validated and delivered:
lifecycle state machines, quality-gate composition, review lanes, lifecycle
procedures, and todo/state semantics. Its documentation is executable contract.
A process change is a behavioral delta to that contract, whether expressed as a
scenario change or as directive text an agent acts on.

Platform behavior does not become process merely because a lifecycle role
observes it. When one change affects an owning context and one process
instruction, classify and govern each consequence separately.

### Process evolution is agent-owned

Agents design, propose, file, prepare, author, and implement process changes.
They ground the change in current contracts and verified substrate, record the
material reason and before/after guarantee in the change description or RFC,
author the process contract before implementation, and carry it through the
ordinary independent review lifecycle.

The process artifact creates no human decision. Apply
`general/policy/human-contract` to the underlying consequence. Only a material
outcome, commitment, risk, scope boundary, exclusive-domain judgment, or
participation-contract change in that closed lane returns to the human. The
agent retains every technical mechanism and never asks the human to approve its
process design.

### Existing review is the control surface

Process changes use the existing review system; no separate approval lane or
human sign-off is introduced. Plan review anticipates every applicable review
lane, build and commit review independently execute them, authors never write
their own verdicts, and ordinary verdict arithmetic blocks on every unresolved
finding.

The reviewer reconstructs the before/after guarantee, verifies the pending
process contract covers the implementation, and challenges violations through
the existing scope, ownership, paradigm, principles, docs, and doc-hygiene
lanes. Evidence supplied by the author directs attention and never substitutes
for independent judgment.

### Relaxing a control requires a no-stake reviewer

A change that removes, bypasses, narrows, delays, or makes non-blocking a
validation or delivery control may be correct, but it receives the same
protection already applied to quality-defining configuration: a separate
reviewer session with no stake in the work the relaxation would unblock must
explicitly approve that relaxation on its merits. The session whose work is
blocked by the control never approves moving it. Strengthening a control follows
ordinary independent review.

This rule adds no review lane and changes no verdict arithmetic. It defines the
authority existing reviewers apply when the reviewed delta is a relaxation.
Maintenance framing, convenience, a spent review count, or perceived alignment
with intent supplies no justification.

### Operation and recovery remain with intelligence

Classifying a halt, selecting remediation ownership, resolving technical
disagreement, authorizing bounded further review, and operating established
recovery provisions are not process changes. They remain agent-owned and never
move to the human because attempts failed or a supported route is missing.

Recovery authority cannot approve unresolved findings, weaken a gate, widen
scope, or forge unsupported state. A missing recovery operation is an
agent-owned tooling problem.

### Repairs are agent-owned

Restoring code to the current process contract is a bug fix. Correcting process
text that contradicts a higher-authority contract or binds an impossible act is
a documentation repair. Neither requires human decision.

A repair report names the contradiction, cites the broken text and every
authority used, and reproduces the clauses that directly carry the corrected
propositions. Anything those clauses do not carry is new design and follows the
ordinary agent-owned process-change path with independent review.

### Process work travels through the normal lifecycle

Agent-originated process work may be filed and prepared like other functional
work. Preparation authors or updates its pending process contract before the
implementation plan. The plan implements that reviewed contract; a builder does
not invent process behavior in a worktree.

A bug whose diagnosed cause is a process defect may correct that defect within
the bug's authorized symptom and causal scope. Adjacent hardening remains scope
expansion and is rejected normally.

## Rationale

- Agents hold the technical knowledge needed to evolve validation and delivery
  mechanics. Assigning that machinery to the human transfers responsibility to
  the participant least able or willing to evaluate it.
- Independent review, complete lane coverage, reviewer separation, citations,
  and blocking verdict arithmetic already form the technical catch. Reusing
  them is stronger and simpler than human approval or a parallel review system.
- The no-stake rule addresses the real conflict: an agent must not lower the wall
  that blocks its own work. It does not make every process improvement suspect.
- Consequence-based ownership preserves the human's actual domain without using
  `process` as a keyword that claims their attention.

## Scope

- All process-layer documentation and implementation in sdlc
  lifecycle projects.

## Enforcement

- A plan implementing process behavior not covered by its current or pending
  process contract is a Requirement-Violation.
- A control relaxation without explicit approval from an independent no-stake
  reviewer is Critical.
- An author approving its own process change or review finding is a violation of
  reviewer separation.
- Asking the human to decide process mechanics is a human-contract finding.
- Taking an underlying human-owned consequence without its decision is the
  corresponding finding from the other side.
- Unresolved findings always retain their ordinary blocking force; neither the
  human nor the author substitutes a technical verdict.

## Exceptions

- None.

## See Also

- ~/.teleclaude/docs/general/policy/human-contract.md
- ~/.teleclaude/docs/sdlc/policy/definition-of-done-lanes.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/review.md
- ~/.teleclaude/docs/general/policy/agent-artifact-governance.md
