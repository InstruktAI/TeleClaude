---
description: 'Schema contract for /projects-analyze enrichment output: discovery-to-taxonomy mapping, snippet ID conventions, file placement, frontmatter template, and merge rules for re-analysis.'
visibility: 'public'
---

# Init Scaffolding — Spec

## What it is

The schema contract between the `/projects-analyze` analysis session (invoked by
`telec projects analyze` or `telec projects onboard`) and the enrichment writer
module. Defines how analysis findings become durable project doc snippets, how
snippet IDs are structured, where files land, and how re-analysis merges without
destroying human edits.

## Canonical fields

### Discovery-to-Taxonomy Mapping

Analysis dimensions map to taxonomy types as guidance. The analysis session
decides which snippets to produce based on what it finds — this mapping is not
a fixed checklist.

| Analysis Dimension                             | Taxonomy Type | Snippet ID Pattern                              |
| ---------------------------------------------- | ------------- | ----------------------------------------------- |
| Bounded context contract                       | `spec`        | `project/spec/domain/{context}`                 |
| User-visible product capability                | `spec`        | `project/spec/feature/{context}/{concept-name}` |
| Architecture patterns, module organization     | `design`      | `project/design/{slug}`                         |
| Naming conventions, code style, error handling | `policy`      | `project/policy/{slug}`                         |
| Dependency inventory, entry points, config     | `spec`        | `project/spec/{slug}`                           |
| Test strategy, coverage model                  | `design`      | `project/design/{slug}`                         |
| Build/deploy pipeline                          | `spec`        | `project/spec/{slug}`                           |
| Operational procedures                         | `procedure`   | `project/procedure/{slug}`                      |

### Snippet ID Conventions

Generated snippet IDs follow these supported shapes:

- `project/{taxonomy}/{slug}` for flat project snippets.
- `project/spec/domain/{context}` for bounded-context domain specs.
- `project/spec/feature/{context}/{concept-name}` for Category A feature specs.

Where:

- `{taxonomy}` is one of: `principle`, `concept`, `policy`, `procedure`, `design`, `spec`.
- `{slug}` is a lowercase kebab-case name derived from the content topic.
- `{context}` is a safe bounded-context identifier using lowercase letters,
  digits, hyphen, or underscore, beginning with a lowercase letter.
- `{concept-name}` is a safe durable product/domain noun using lowercase
  letters, digits, hyphen, or underscore, beginning with a lowercase letter.
- IDs must be unique within the project scope.
- IDs must not collide with existing manually authored snippet IDs.
- IDs must not contain empty path segments, `.` segments, `..` segments, or any
  other path traversal. File destinations must still resolve under
  `docs/project/`.

Reserved snippet IDs (standard set, used as applicable):

```
project/design/architecture
project/design/test-strategy
project/policy/conventions
project/spec/dependencies
project/spec/entry-points
project/spec/build-deploy
project/spec/configuration
```

### File Placement

Generated snippets are placed under `docs/project/` following the taxonomy
directory structure:

```
docs/project/
  design/
    architecture.md
    test-strategy.md
  policy/
    conventions.md
  spec/
    dependencies.md
    entry-points.md
    build-deploy.md
    configuration.md
    domain/
      workflow.md
    feature/
      workflow/
        todo-management.md
  procedure/
    (as needed)
```

Taxonomy directories are created on demand. The baseline directories that the
enrichment writer ensures exist are: `design/`, `policy/`, `spec/`.

### Frontmatter Template

Every generated snippet must include this frontmatter:

```yaml
---
id: 'project/{taxonomy}/{slug}'
type: '{taxonomy}'
scope: 'project'
description: '{concise description of what this snippet documents}'
generated_by: 'telec-init'
generated_at: '{ISO8601 timestamp}'
---
```

Required fields: `id`, `type`, `scope`, `description`, `generated_by`,
`generated_at`.

- `generated_by: telec-init` marks the snippet as auto-generated.
- `generated_at` records when the snippet was last generated or refreshed.
- Generated snippets describe current behavior; absence of `delivered_by`
  is the current-state signal. Design-delivery snippets that describe intended
  future state carry `delivered_by: [<owning-slug>]`; analysis does not
  generate those.
- `scope` is always `project` for enrichment-generated snippets.

### Merge Rules for Re-analysis

When enrichment runs on a project that already has auto-generated snippets:

1. **Identify existing snippets** by checking for `generated_by: telec-init`
   in frontmatter.
2. **Human-authored sections survive.** Any content after a `<!-- human -->` marker
   in an existing snippet is preserved verbatim during merge. The analysis session
   regenerates only the auto-generated sections above the marker.
3. **Changed-file-only writes.** If the merged output is identical to the existing
   file content, do not rewrite the file (preserve timestamps).
4. **No duplication.** Re-analysis updates existing snippets by ID rather than
   creating new files with different names.
5. **New snippets are additive.** If the re-analysis discovers aspects not covered
   by existing snippets, new snippets are created normally.
6. **Removed snippets are preserved.** If a re-analysis no longer produces a
   snippet that previously existed, the existing file is kept (it may contain
   human edits). The metadata file tracks which snippets were generated vs. preserved.

### Agent Bootstrap Content

The enrichment writer's behavior is governed by the AGENTS.master.md decision
in `software-development/procedure/project-analysis` (Step 15). The four
normal cases plus the anomaly:

- **Case 1 — `AGENTS.master.md` exists.** The existing artifact source is
  authoritative. The enrichment writer does not modify it.
- **Case 2 — Hand-authored `AGENTS.md` exists, no master.** The enrichment
  writer promotes it: the existing `AGENTS.md` content is moved into a new
  `AGENTS.master.md`. Subsequent `telec sync` regenerates `AGENTS.md`
  (possibly with baseline additions) and writes the `CLAUDE.md` shim. By
  convention `CLAUDE.md` is a shim or absent in this case.
- **Case 3 — Substantive standalone `CLAUDE.md`, no `AGENTS.md`.** The
  enrichment writer does not create a master. A substantive standalone
  `CLAUDE.md` is a deliberate Claude-Code-only signal. Promotion is possible
  only as an explicit human-driven step.
- **Case 4 (greenfield) — none of the above.** The enrichment writer generates
  a minimal project-specific `AGENTS.master.md` (tech stack, key directories,
  primary conventions). Normal artifact inflation then produces `AGENTS.md`
  and the `CLAUDE.md` shim at sync time.

**Anomaly — both substantive `AGENTS.md` and substantive `CLAUDE.md`.** This
contradicts the shim convention. The enrichment writer halts and flags the
conflict for human inspection. It does not auto-promote: a subsequent
`telec sync` would overwrite `CLAUDE.md` with the shim and silently destroy
its content.

### Validation Contract

The enrichment writer validates all output before persistence:

- Snippet IDs must match one of the supported flat or nested project ID shapes.
- File destinations must resolve to paths under `docs/project/`.
- Frontmatter must contain all required fields.
- Unknown or unsafe snippet IDs (those that would escape `docs/project/`) are
  rejected before any file write.

### Metadata File

The enrichment writer persists `.telec-init-meta.yaml` in the project root:

```yaml
last_analyzed_at: '2024-01-15T10:30:00Z'
analyzed_by: telec-init
files_analyzed: 42
snippets_generated:
  - project/design/architecture
  - project/policy/conventions
  - project/spec/dependencies
snippets_preserved:
  - project/spec/entry-points
```

This file is read during re-analysis to inform merge decisions and is updated
after each enrichment run.
