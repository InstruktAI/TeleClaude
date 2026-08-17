---
description: Function-level use-case declarations that let the Blueprint join structural dependencies to shared behavioral intent without copying behavior into source comments.
delivered_by:
  - code-uc-blueprint-traceability
---

# Implementation Behavior Map — Spec

## What it is

The implementation behavior map connects behavior-bearing Python functions to the use cases they
realize or materially support. A mapped function carries a compact terminal docstring footer containing
only use-case identities that are unique within the project's effective documentation
view. The Blueprint combines those declared
behavioral relationships with its structural dependency graph so agents can see
implementation locations that share intent even when imports and calls do not
connect them.

The map supplies facts and mechanically derived candidates. Specifications remain
the sole source of behavioral prose, while agents judge relevance, conflicts,
duplication, missing contracts, and refactoring opportunities from the feature
and domain context.

## Canonical fields

### Function footer

A new or changed function that materially realizes or gates an observable
use-case outcome has a docstring whose terminal metadata line uses this exact
shape:

```python
"""
UC: UC-TAAV-1@r1, UC-SVIS-2@r1
"""
```

The comma-separated values are exact use-case identities from the project's
selected effective documentation view, with explicit revisions and
sorted by identity. The footer contains no snippet paths, source paths,
titles, behavioral prose, or explanations. Multiple functions may declare the
same use case, and one function may declare multiple use cases.

A use case applies to a function when changing that function's behavior could
change whether the use case passes. This includes observer-facing seams and
private helpers that materially control the outcome; incidental reuse or merely
appearing in the call tree does not make a use case applicable. A helper cites
the behavior it participates in rather than acquiring an implementation-level
use case. Aptness is reconciled by the agent from the defining and domain
specifications. Mechanical validation proves identity, revision, and grammar
facts only; it never judges semantic aptness or requires a declaration solely
because a function body changed.

### Resolution

The current or todo-target documentation view supplies an ephemeral catalog from
use-case identity to its defining specification. Source parsing supplies the
function, source location, and declared identities. Neither relationship is
stored as a durable index.

The affected view starts with the changed Python functions and the existing
structural result, collects the use cases declared by those functions, then scans
every source function for those identities. Matching functions absent from the
structural graph are added as shared-use-case locations. An agent may also start
from an exact use-case identity or a changed specification and receive every
function declaring the referenced identities. Expansion stops after that reverse
lookup; other use cases co-located on newly found functions do not trigger
recursive expansion.

Changed-function declarations and their shared-use-case locations remain
available when the structural manifest is missing or stale. The command preserves
the structural fallback as a separate fact; unavailable structural edges do not
suppress source-resolvable behavioral facts.

### Output boundaries

The affected view separates structural dependents, shared-use-case locations,
and unannotated functions with directly adjacent declarations. It reports exact
identities, defining specification IDs, source locations, and structural-edge
provenance. It does not inline Gherkin, summarize behavior, infer mappings, rank
candidates, or report a completeness percentage.

For an unannotated changed function or function in the structural result,
identities declared by its direct callers and callees are candidate facts. The agent reads the resolved
specifications and relevant domain specs before deciding whether the function
implements an existing use case, exposes a missing contract, conflicts with
another use case, or belongs in a refactoring opportunity.

### Validation and adoption

Documentation synchronization validates two distinct universes. The authored
identity-claim corpus includes dirty canonical source, planned and planned-change
blocks, and companion bodies, while excluding generated projections. It reserves
every pending identity and rejects competing claims, while treating the current
and replacement halves of one planned-change block and a companion's replacement
of its own base as one lineage. The effective resolution view selects the live,
todo-target, or folded-integration projection against which existing function
declarations are checked for footer grammar, specification resolution, and
revision currency.

A semantic use-case revision is atomic in the delivery candidate: the revised
specification and every declaration bound to the superseded revision resolve
together before that candidate passes. The still-live projection and its current
source declarations remain valid while the replacement is pending. Scoped code
quality review reconciles every new or body-changed function. It requires a
footer when the function materially realizes or gates a use-case outcome, and
records an explicit no-specific-lineage judgment in review evidence when it does
not; that judgment leaves no exemption marker in source. Review rejects false or
stale lineage, while code does not invent a semantic missing-footer validator.
An applicable use case that does not yet exist is a documentation gap to author,
not a vacancy marker. Unmapped
functions remain available as reconciliation candidates rather than blocking
unrelated work.

### Use cases

#### UC-IBM-1: Shared behavior expands structural discovery

```gherkin
Given an agent asks for the affected view of changed source
And changed functions or functions in the structural result declare one or more use cases
When the affected view resolves those declarations
Then the structural dependents remain visible
And every source function declaring the same use cases is also visible
And locations absent from the structural result are distinguished by their shared-use-case provenance
```

#### UC-IBM-1b: Behavioral facts survive an unavailable structural baseline

```gherkin
Given the Blueprint manifest is missing or stale
And a changed Python function declares one or more use cases
When the affected view is produced
Then the structural fallback remains visible
And every source function declaring the changed function's use cases is still visible
And no unavailable structural edge is implied
```

#### UC-IBM-2: Behavioral context stays canonical and lean

```gherkin
Given the affected view resolves a declared use case
When it presents that use case to an agent
Then it shows the exact use-case identity and defining specification identity
And it shows the source locations that declared the use case
And it does not reproduce or summarize the use case's behavioral prose
```

#### UC-IBM-3: Unannotated functions expose evidence-backed candidates

```gherkin
Given a changed function or a function in the structural result has no use-case declaration
And a direct caller or callee declares one or more use cases
When the affected view presents reconciliation candidates
Then it shows the unannotated function
And it shows the adjacent use-case identities with their structural-edge provenance
And it does not assert that any candidate governs the function
```

#### UC-IBM-4: Authored declarations remain mechanically resolvable

```gherkin
Given the documentation and source corpus contain use-case identities and function declarations
When documentation synchronization validates the corpus
Then competing use-case identity claims are rejected while alternatives in one replacement lineage remain valid
And malformed, unknown, or revision-stale function declarations are rejected
And absent declarations do not invalidate synchronization
```

#### UC-IBM-5: Changed functions reconcile behavioral lineage

```gherkin
Given an agent adds or changes a Python function while delivering observable behavior
When scoped code quality review evaluates the change
Then each added or body-changed function is explicitly reconciled
And a function that materially realizes or gates a use-case outcome has a terminal footer containing only current, resolvable identities whose outcomes its behavior can change
And the agent has reconciled those identities against the defining and domain specifications
And a function with no specific behavioral lineage is recorded as such in review evidence without claiming an unrelated use case or carrying an exemption marker in source
```

#### UC-IBM-6: A use case exposes its implementation surface

```gherkin
Given an agent starts from an exact use-case identity or a changed specification containing use cases
When the Blueprint resolves the implementation view
Then it shows the defining specification and every source function declaring those exact identities and revisions
And it distinguishes those declaration facts from structural dependency claims
And no identity merely sharing a prefix is included
```
