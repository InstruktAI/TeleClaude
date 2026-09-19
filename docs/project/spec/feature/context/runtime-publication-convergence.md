---
description: Fleet-wide reconciliation of registered artifact and documentation sources into runtime outputs from one location-independent synchronization run.
visibility: internal
delivered_by:
  - fleet-artifact-sync
---

# Runtime Publication Convergence — Spec

## Required reads

- @docs/project/spec/domain/context.md
- @docs/project/spec/feature/context/sync-pipeline-orchestration.md

## What it is

One synchronization request reconciles every configured source root that
participates in artifact or documentation publication. Reconciliation derives
the fleet from authoritative registration and tier declarations, so the result
does not depend on the directory from which the request was made and does not
discover publishers by scanning the filesystem.

The Context area owns fleet enumeration, orchestration, source validation, and
publication. Each source root keeps its own capability gates and permitted
outputs; the composed documentation contract retains source-backed reference
resolution, serialization, and atomic replacement of the deployed snapshot.

## Canonical fields

- **Fleet roots:** the mother source root, present project roots named by the
  project registry, and configured company and person homes at their declared
  conventional locations.
- **Enumeration authority:** project registration and tier declarations. An
  unrelated checkout or home directory is not a publisher merely because it is
  present on the filesystem.
- **Execution contract:** every participating root is reconciled through its
  published root-local synchronization contract and capability gates.
- **Documentation safety:** validation resolves documentation references through
  registered publisher sources, and deployment replaces the composed
  documentation tree as one complete snapshot.

### Use cases

#### UC-RPC1: One request reconciles the configured fleet from any location

```gherkin
Given the mother source, registered projects, and configured company and person homes contain publishable sources
When an operator requests synchronization from any working directory
Then every participating source root is reconciled into the outputs its tier and capabilities permit
And the participating root set and resulting outputs do not change with the invocation directory
```

#### UC-RPC2: Fleet membership comes only from authoritative declarations

```gherkin
Given the project registry and tier declarations identify the configured publication roots
And another source-shaped directory exists elsewhere on the filesystem
When synchronization determines the fleet to reconcile
Then it includes every present declared publication root
And it does not include the unrelated directory
And it performs no filesystem scan to discover additional roots
```

#### UC-RPC3: Fleet reconciliation preserves source-first validation and complete publication

```gherkin
Given a registered publisher contains a valid reference that has not yet been deployed
And the composed documentation tree may be read while synchronization runs
When fleet reconciliation validates and publishes the configured roots
Then the reference is resolved against its registered publisher source
And generated documentation required by publication is produced before dependent outputs are replaced
And a runtime reader observes either the complete prior documentation snapshot or the complete replacement snapshot
```

## Known caveats

- Fleet reconciliation coordinates root-local capability contracts; it does
  not define company, person, project, or global artifact reach.
- A root that is declared but unavailable is not discovered by searching for an
  alternate checkout. Availability handling belongs to the fleet orchestrator
  and must preserve the authoritative registration record.
