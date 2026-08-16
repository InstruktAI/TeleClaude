---
description: Function-level use-case declarations that let the Blueprint join structural dependencies to shared behavioral intent without copying behavior into source comments.
delivered_by:
  - code-uc-blueprint-traceability
---

# Implementation Behavior Map — Spec

## What it is

The implementation behavior map connects Python functions to the use cases they
realize or materially support. Each function carries a compact terminal docstring footer containing
only use-case identities that are unique within the project's effective published
documentation corpus. The Blueprint combines those declared
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

The comma-separated values are use-case identities that are unique within the
project's effective published documentation corpus, with explicit revisions and
sorted by identity. The footer contains no snippet paths, source paths,
titles, behavioral prose, or explanations. Multiple functions may declare the
same use case, and one function may declare multiple use cases.

A use case applies to a function when changing that function's behavior could
change whether the use case passes. This includes observer-facing seams and the
private helpers that materially support them; a helper cites the behavior it
participates in rather than acquiring an implementation-level use case. Aptness
is reconciled by the agent from the defining and domain specifications. Mechanical
validation proves identity, revision, and grammar facts only; it never judges
semantic aptness.

### Resolution

The current or todo-target documentation view supplies an ephemeral catalog from
use-case identity to its defining specification. Source parsing supplies the
function, source location, and declared identities. Neither relationship is
stored as a durable index.

The affected view starts with the changed Python functions and the existing
structural result, collects the use cases declared by those functions, then scans
every source function for those identities. Matching functions absent from the
structural graph are added as shared-use-case locations. Expansion stops after
that reverse lookup; other use cases co-located on newly found functions do not
trigger recursive expansion.

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

For an unannotated function in the structural result, identities declared by its
direct callers and callees are candidate facts. The agent reads the resolved
specifications and relevant domain specs before deciding whether the function
implements an existing use case, exposes a missing contract, conflicts with
another use case, or belongs in a refactoring opportunity.

### Validation and adoption

Documentation synchronization validates the complete set of authored UC
identities and existing function declarations visible in the project's effective
published corpus: identity uniqueness, footer grammar, specification resolution,
and revision currency. A semantic use-case revision is an atomic corpus change:
the revised specification and every existing source declaration bound to the
superseded revision must migrate together before synchronization passes. Scoped
code quality validation requires every new function and every changed existing
function to leave with at least one current, resolvable identity in its footer.
An applicable use case that does not yet exist is a documentation gap to author,
not a vacancy marker or an exemption. Untouched unannotated legacy functions
remain available as reconciliation candidates rather than blocking unrelated
work.

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
Then the function has a terminal use-case footer containing only current, resolvable use-case identities
And the footer contains at least one identity
And each identity governs a use case whose outcome can change when the function's behavior changes
And the agent has reconciled those identities against the defining and domain specifications
```
