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

## Primary flows

### Readiness check

Goal:

- admit only locally valid reviewed changes into integration consideration

How rigor is preserved:

- branch-local quality gates are already satisfied before integration begins

### Queue and compatibility check

Goal:

- understand overlap, dependency, ordering sensitivity, and system risk

How rigor is preserved:

- the change is evaluated in concurrent delivery context instead of in
  isolation

### Sequencing and cutover

Goal:

- decide whether to land now, reorder, batch, or require revalidation

How rigor is preserved:

- delivery order becomes an explicit system decision
- cutover is treated as a controlled convergence step, not as a merge button

### Post-integration verification

Goal:

- confirm that the landed system remains coherent after actual cutover

How rigor is preserved:

- integration validates system truth after landing, not only before it

## Failure modes

- approved branch-local changes are landed in unsafe or conflicting order
- teams optimize for local readiness instead of system absorbability
- late concurrency conflicts invalidate already-reviewed work
- mainline instability is caused by delivery order rather than isolated code quality

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/integrate.md —
  operational steps for executing the integration phase
