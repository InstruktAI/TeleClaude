---
id: 'software-development/design/sdlc/integration'
type: 'design'
domain: 'software-development'
scope: 'global'
description: 'Integration phase design: concurrency-aware landing, sequencing, and system-level convergence for reviewed changes.'
---

# Integration — Design

## Required reads

- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define how reviewed branch-local changes become safe system truth under
high-volume concurrent delivery.

Integration exists because reviewed local validity is not enough when many
changes compete to land on the same mainline.

## Inputs/Outputs

**Inputs**

- reviewed, approved change(s)
- current mainline state
- queued or recently landed concurrent changes

**Outputs**

- ordered landing decision
- integrated mainline change
- post-integration system state

## Invariants

- Approval in isolation is necessary but not sufficient for landing.
- Integration is responsible for system-level convergence under concurrency.
- Sequencing and cutover safety must be explicit rather than accidental.
- Integration exists to absorb delivery friction created by high-volume
  concurrent software production.
- Integration may later use a stronger lead/support split, but the current
  design requirement is that both the system-outcome concern and the sequencing
  concern are explicitly represented.

## Primary flows

### Readiness check

Goal:

- admit only locally valid reviewed changes into integration consideration

How rigor is preserved:

- branch-local quality gates are already satisfied before integration begins

Automation supplies:

- queue state, branch state, and mechanical readiness evidence

Human/AI touchpoint:

- AI can evaluate readiness mechanically and operationally
- humans enter when delivery timing or risk acceptance requires explicit
  judgment

### Queue and compatibility check

Goal:

- understand overlap, dependency, ordering sensitivity, and system risk

How rigor is preserved:

- the change is evaluated in concurrent delivery context instead of in
  isolation

Automation supplies:

- overlap signals, dependency signals, recent landing context, and other
  computable delivery facts

Human/AI touchpoint:

- AI can surface compatibility and ordering concerns
- humans enter when overlap creates product, organizational, or release-level
  trade-offs

Why this exists:

- multiple valid local changes can still conflict in landing order, shared
  surfaces, or timing against the mainline

### Sequencing and cutover

Goal:

- decide whether to land now, reorder, batch, or require revalidation

How rigor is preserved:

- delivery order becomes an explicit system decision
- cutover is treated as a controlled convergence step, not as a merge button

Automation supplies:

- candidate sequences, cutover evidence, and mechanical revalidation where
  possible

Human/AI touchpoint:

- AI can drive sequencing and cutover decisions
- humans enter when landing order has product, release, or risk implications

Exit condition:

- the system has a deliberate landing decision, not just a technically possible
  merge

### Post-integration verification

Goal:

- confirm that the landed system remains coherent after actual cutover

How rigor is preserved:

- integration validates system truth after landing, not only before it

Automation supplies:

- post-landing checks, scope evidence, and other mechanical confirmation

Human/AI touchpoint:

- AI can verify system coherence against explicit checks
- humans enter when post-landing behavior raises product or operational
  questions

### Integration emphasis matrix

| Step                          | Main question                                             | Primary concern             | Rigor mechanism                                               |
| ----------------------------- | --------------------------------------------------------- | --------------------------- | ------------------------------------------------------------- |
| readiness                     | Is this change locally valid enough to consider?          | branch-local truth          | reviewed quality is a precondition, not the whole answer      |
| compatibility                 | Can the system absorb this change now?                    | system outcome + sequencing | changes are evaluated in concurrent context, not in isolation |
| cutover                       | In what order and under what conditions should this land? | system outcome + sequencing | delivery order becomes explicit and controlled                |
| post-integration verification | Did the landed system remain coherent?                    | system truth after landing  | actual cutover outcome is verified, not assumed               |

## Failure modes

- approved branch-local changes are landed in unsafe or conflicting order
- teams optimize for local readiness instead of system absorbability
- late concurrency conflicts invalidate already-reviewed work
- mainline instability is caused by delivery order rather than isolated code quality
- integration is reduced to “merge after approval” and loses its concurrency
  management purpose

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/integrate.md —
  operational steps for executing the integration phase
