---
description: Function-level use-case declarations that let the Blueprint join structural dependencies to shared behavioral intent without copying behavior into source comments.
delivered_by:
  - code-uc-blueprint-traceability
---

# Implementation Behavior Map — Spec

## What it is

The implementation behavior map connects Python functions to the use cases they
realize. Each function carries a compact terminal docstring footer containing
only globally unique use-case identities. The Blueprint combines those declared
behavioral relationships with its structural dependency graph so agents can see
implementation locations that share intent even when imports and calls do not
connect them.

The map supplies facts and mechanically derived candidates. Specifications remain
the sole source of behavioral prose, while agents judge relevance, conflicts,
duplication, missing contracts, and refactoring opportunities from the feature
and domain context.

## Canonical fields

### Function footer

Every new function, and every existing function whose body is changed, has a
docstring whose terminal metadata line uses this exact shape:

```python
"""
UC: UC-TAAV-1@r1, UC-SVIS-2@r1
"""
```

The comma-separated values are globally unique use-case identities with explicit
revisions, sorted by identity. The footer contains no snippet paths, source paths,
titles, behavioral prose, or explanations. Multiple functions may declare the
same use case, and one function may declare multiple use cases.

### Resolution

The current or todo-target documentation view supplies an ephemeral catalog from
use-case identity to its defining specification. Source parsing supplies the
function, source location, and declared identities. Neither relationship is
stored as a durable index.

The affected view starts with the existing structural result, collects the use
cases declared by functions in that result, then scans every source function for
those identities. Matching functions absent from the structural graph are added
as shared-use-case locations. Expansion stops after that reverse lookup; other
use cases co-located on newly found functions do not trigger recursive expansion.

### Output boundaries

The affected view separates structural dependents, shared-use-case locations,
and unannotated functions with directly adjacent declarations. It reports exact
identities, defining specification IDs, source locations, and structural-edge
provenance. It does not inline Gherkin, summarize behavior, infer mappings, rank
candidates, or report a completeness percentage.

For an unannotated function in the structural result, identities declared by its
direct callers and callees are candidate facts. The agent reads the resolved
specifications and relevant domain specs before deciding whether the function
implements an existing use case, exposes a missing contract, conflicts with
another use case, or belongs in a refactoring opportunity.

### Validation and adoption

Documentation synchronization validates the complete set of authored UC
identities and existing function declarations: identity uniqueness, footer
grammar, specification resolution, and revision currency. Scoped code quality
validation requires every new function and every changed existing function to
leave with a reconciled footer. Untouched legacy functions remain available as
reconciliation candidates rather than blocking unrelated work.

### Use cases

#### UC-IBM-1: Shared behavior expands structural discovery

```gherkin
Given an agent asks for the affected view of changed source
And functions in the structural result declare one or more use cases
When the affected view resolves those declarations
Then the structural dependents remain visible
And every source function declaring the same use cases is also visible
And locations absent from the structural result are distinguished by their shared-use-case provenance
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
Given a function in the structural result has no use-case declaration
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
Then duplicate use-case identities are rejected
And malformed, unknown, or revision-stale function declarations are rejected
And absent declarations on untouched legacy functions do not invalidate synchronization
```

#### UC-IBM-5: Changed functions reconcile behavioral lineage

```gherkin
Given an agent adds a function or changes an existing function body
When scoped code quality validation evaluates the change
Then the function has a terminal use-case footer containing only current use-case identities
And the agent has reconciled those identities against the defining and domain specifications
```
