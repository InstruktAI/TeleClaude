---
description: Lifecycle-derived use-case traceability joining stable specification identities to approved plans, delivery commits, and Blueprint structure without source annotations.
delivered_by:
  - code-uc-blueprint-traceability
---

# Implementation Traceability — Spec

## What it is

Implementation traceability lets agents move between a use case and the code
deliveries associated with it without copying behavioral identity into source
files. The Workflow lifecycle already binds feature-spec use cases to approved
implementation-plan tasks and records the commit that actually delivered each
todo. Blueprint composes those facts with Git history and its structural graph.

The result is evidence, not semantic authorship. A plan states intended scope, a
delivery commit states which paths changed, and Blueprint states structural
reach. The defining feature and domain specifications remain the authority for
what the behavior means.

## Canonical fields

### Stable reference and lifecycle anchors

A use case is addressed by the exact composite `spec_id + UC-id`. The UC id is
unique only within its defining specification. Prefix similarity and a matching
UC id in another specification create no relationship.

Before delivery, approved implementation-plan tasks associate use cases with
their declared referenced paths and observation-map evidence. After delivery,
the todo record supplies the delivery commit and that commit's diff supplies the
actual changed paths. The projection reports both when they differ; it never
rewrites either source.

### Predicate drift from Git history

For a delivered association, the projection reads the fenced Gherkin block for
the same composite identity from the delivery commit and compares its canonical
content with the selected current or todo-target block. A difference reports
that the predicate changed after the linked delivery. A missing historical or
current block reports unavailable evidence.

The comparison is derived at query time. Use-case headings carry no revision
number, source files carry no use-case tag or fingerprint, and synchronization
does not require a metadata migration when a predicate or implementation moves.

### Code-originated view

Starting from changed source paths, the projection finds in-flight approved
plans whose referenced paths include them and delivered todos whose actual
delivery diffs include them. It reports the exact use cases those plans bind,
the todo and commit provenance, and the predicate-drift state. The source paths
may seed the existing Blueprint affected view, whose structural dependents stay
a separate evidence class.

### Use-case-originated view

Starting from an exact composite use-case reference, the projection reports its
defining specification, linked approved plans, delivered todos and commits, and
the actual source paths changed by those deliveries. Those paths may seed the
existing Blueprint affected view. Plan linkage, commit membership, and graph
reach never become a claim that a particular function implements the behavior.

### Honesty boundaries

An absent association is shown as missing traceability evidence, not proof that
the use case has no implementation. An association whose predicate changed is
shown as stale evidence, not a synchronization failure. The projection does not
infer mappings from call adjacency, require annotations on changed functions,
assign global UC identities, or report coverage percentages.

### Use cases

#### UC-IT1: Changed code exposes lifecycle-linked behavior

```gherkin
Given an agent starts from one or more changed source paths
When the implementation traceability view is produced
Then it shows exact use cases linked by approved in-flight plans or delivered commits touching those paths
And it distinguishes intended plan paths from actual delivery paths
And structural dependents remain a separate evidence class
```

#### UC-IT2: A use case exposes linked implementation deliveries

```gherkin
Given an agent starts from an exact specification identity and UC id
When the implementation traceability view is produced
Then it shows the defining specification, linked plans, delivered todos, delivery commits, and actual changed source paths
And those source paths can seed the existing Blueprint affected view
And a matching UC id in another specification is not included
```

#### UC-IT3: Predicate drift is derived without authored revisions

```gherkin
Given a delivered todo linked a use case to a delivery commit
And the current fenced Gherkin predicate differs from that delivery commit's predicate for the same composite identity
When the implementation traceability view is produced
Then it reports that the predicate changed after the linked delivery
And it identifies both Git snapshots used for the comparison
And no use-case revision number, stored fingerprint, or source metadata migration is required
```

#### UC-IT4: Refactors require no traceability annotation migration

```gherkin
Given a behavior-preserving refactor moves or rewrites implementation code
When the refactor is reviewed and delivered
Then source files require no use-case footer, tag, or fingerprint update
And traceability continues to derive from approved plan evidence, delivery commits, Git history, and Blueprint structure
```

#### UC-IT5: Missing evidence remains explicit

```gherkin
Given no approved plan or delivered todo links a queried use case or source path
When the implementation traceability view is produced
Then it reports that no lifecycle association was found
And it does not conclude that the behavior has no implementation or that the source has no behavioral responsibility
```

## Known caveats

- Delivery-commit membership is file-level provenance, not function-level semantic proof.
- Historical todos whose retained artifacts or delivery commits are unavailable
  cannot contribute complete traceability and are reported as unavailable.
- A refactor with no use-case references in its approved plan may rely on Git
  move detection and structural reach only; the projection reports that weaker
  provenance rather than inventing a behavioral link.
