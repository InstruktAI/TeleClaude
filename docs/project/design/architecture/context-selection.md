---
description: 'Context selection pipeline that picks relevant docs for the two-phase context retrieval flow.'
visibility: 'public'
---

# Context Selection — Design

## Purpose

- Select relevant documentation docs for a given request.

- Selected IDs must exist in the snippet index.
- Requires dependencies are always expanded before output.

- Build snippet metadata from docs and global docs.
- Return a filtered index (frontmatter only) when no IDs are provided.
- Accept selected snippet IDs from the caller and resolve requires dependencies.
- Order by scope priority (global -> domain -> project).
- Persist selected IDs per session to avoid repeated context churn.

```mermaid
flowchart TB
    ContextClient["Context Client"]
    Phase1["Phase 1:<br/>index query (areas)"]
    Phase2["Phase 2:<br/>content query (snippet_ids)"]
    Index["docs/index.yaml"]
    Files["Snippet MD files"]

    ContextClient -->|areas filter| Phase1
    Phase1 -->|read| Index
    Phase1 -->|return| ContextClient
    ContextClient -->|selected IDs| Phase2
    Phase2 -->|read| Files
    Phase2 -->|resolve requires| Files
    Phase2 -->|return| ContextClient
```

## Inputs/Outputs

**Inputs:**

- **Phase 1**: Optional `areas` array (taxonomy type filter: principle, concept, policy, procedure, design, spec)
- **Phase 2**: `snippet_ids` array of selected snippets to retrieve
- Caller session ID for context persistence
- Project working directory

**Outputs:**

- **Phase 1**: Index listing (ID, description, type, scope) - frontmatter only
- **Phase 2**: Full snippet content with resolved requires dependencies
- Ordered by scope priority: global → domain → project

## Invariants

- **Two-Phase Protocol**: Always phase 1 (index) first, then phase 2 (content).
- **Requires Expansion**: All transitive dependencies included automatically; caller never manually resolves requires.
- **Scope Ordering**: Global snippets before domain before project; stable deterministic order.
- **Duplicate Prevention**: Each snippet ID appears exactly once in output even if required multiple times.

## Primary flows

### 1. Phase 1: Index Retrieval (Discovery)

```mermaid
sequenceDiagram
    participant AI
    participant Selector
    participant Index

    AI->>Selector: telec docs index --areas policy,concept
    Selector->>Index: Load docs/index.yaml
    Selector->>Selector: Filter by areas
    Selector->>Selector: Build frontmatter list
    Selector->>AI: Return [{id, description, type, scope}, ...]
```

### 2. Phase 2: Content Retrieval with Requires Resolution

```mermaid
sequenceDiagram
    participant AI
    participant Selector
    participant FS

    AI->>Selector: telec docs get arch/system policy/version-control
    Selector->>Selector: Expand requires transitively
    Selector->>Selector: Deduplicate and order
    loop For each snippet
        Selector->>FS: Read markdown file
        FS->>Selector: Return content
    end
    Selector->>AI: Return full snippet texts
```

#### Baseline Filtering (Optional)

By default, all snippets including baseline are shown in the phase-1 index.
`telec docs index --baseline-only` filters to baseline snippets only
(those referenced in `baseline.md` manifests). This focused view is useful for
authoring/editing baseline content.

### 3. Requires Expansion Algorithm

```python
def expand_requires(snippet_id, visited=set()):
    if snippet_id in visited:
        return  # Prevent cycles
    visited.add(snippet_id)

    snippet = load_snippet(snippet_id)
    for required_id in snippet.requires:
        expand_requires(required_id, visited)

    yield snippet
```

### 4. Scope Priority Ordering

| Scope   | Priority | Rationale                                   |
| ------- | -------- | ------------------------------------------- |
| global  | 1        | Foundational policies apply universally     |
| domain  | 2        | Domain-specific rules constrain projects    |
| project | 3        | Project details reference global foundation |

<!-- planned:docs-tier-layering -->
### 5. Caller-Scope Resolution

Source assembly is preceded by resolving the caller into a set of reachable
tiers. The stage takes the resolved person from identity and the declared
relationships from configuration, and returns the tiers in reach paired with the
depth each is read at. Nothing downstream re-derives reach: assembly loads the
tiers the stage named, and the include predicate applies the depth it assigned.

The stage is the only place the two inputs meet, which is what keeps the
relationship facts owned by their declaring contexts while the reach rule stays
here.

**Layer placement.** The command surface translates a call into a resolved
caller and passes it inward; it decides no reach. The resolution stage decides.
Catalog loading executes what it decided. A surface that inspects a relationship
to choose what to load has taken a decision that is not its own.

**Selector authorization.** Naming a person or a company tier explicitly is
reserved to platform administrators, and the refusal is a refusal rather than a
silent narrowing — a caller who may not use the selector is told so instead of
receiving a smaller answer that looks like the tier is empty. This gate lives
here rather than with command clearance: clearance authorizes a verb, and this
authorizes what one argument to that verb may reach.

### 6. Tier-Qualified Identity

A snippet's identity carries its tier as the first segment. For the person and
company tiers the identity also carries which person or which company it belongs
to, because more than one tier of the same kind can be present in one assembled
index at the same time — a caller belonging to several companies always
assembles several, and an administrator naming another person's tier assembles
theirs alongside their own. An unqualified identity would make that state
ambiguous, so the qualification is what keeps two tiers from naming the same
thing.

This deliberately diverges from how a foreign project's identity is formed,
where the tier marker is exchanged for the project's slug at load time. That
form works there because exactly one project tier is ever the caller's own and
project slugs are registered in a single manifest. Neither holds for companies:
there is no own company, and a bare slug segment would put company identities
into the same namespace as project identities, where a company and a project
sharing a name would collide. Keeping the tier marker in front and adding the
identity behind it avoids inventing that collision.

The company tier's current identity form is unqualified. Changing it is free
today because no company snippet exists anywhere on disk, and the cost of
changing it rises with the first one authored.

### 7. Tier Catalog Construction

Every tier that carries documentation has its catalog built by the same
publication pass that builds the project and global catalogs. Whether a
non-project tier carries documentation is read from that tier's own capability
declaration, never inferred from its location on disk — inferring it from
location is the meaning-from-location model the tier design exists to remove.

A tier whose catalog is never built is indistinguishable from a tier with no
content, which is the failure the company tier has been in since it landed: its
builder exists, nothing calls it, and no company catalog has ever been written.
Wiring construction is therefore part of introducing a tier, not a later step.
<!-- /planned:docs-tier-layering -->

## Failure modes

- **Snippet Not Found**: Requested ID not in index. Returns error with missing ID list. Client must re-select.
- **File Read Error**: Snippet in index but file missing/unreadable. Skipped with warning. Partial results returned.
- **Invalid ID Format**: Malformed snippet ID. Rejected immediately with error.
- **Index Not Found**: `docs/index.yaml` missing. Returns empty result with error message. Agent cannot proceed.
- **Context Too Large**: Expanded content exceeds AI context window. No automatic truncation. Client must reduce selection.
- **Session Context Loss**: Persisted IDs not found in index after regeneration. Falls back to phase 1 discovery.

<!-- planned:docs-tier-layering -->
- **Unresolvable Caller**: The call carries no identity that resolves to a
  person. The caller holds no relationship to any tier and reads only what
  snippets declare public. Absent identity never widens a read.
- **Declared-but-absent tier**: A relationship names a person or company with no
  configuration present. The misconfiguration is surfaced rather than silently
  producing an empty tier, which is indistinguishable from a correctly empty one.
- **Scope read from location**: Deriving reach from the working directory
  produces an authorization answer that changes when someone changes directory,
  which is not an authorization answer at all.
<!-- /planned:docs-tier-layering -->
