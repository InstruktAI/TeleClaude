---
description: 'Schema contract for sdlc/procedure/project-analysis enrichment output: discovery-to-taxonomy mapping, snippet ID conventions, file placement, frontmatter template, and merge rules for re-analysis.'
visibility: 'public'
---

# Init Scaffolding — Spec

## What it is

The schema contract between the `sdlc/procedure/project-analysis` analysis session (started with
`telec sessions run --command sdlc/procedure/project-analysis`) and the enrichment writer
module. Defines how analysis findings become durable project doc snippets, how
snippet IDs are structured, where files land, and how re-analysis merges without
destroying human edits.

## Canonical fields

### Discovery-to-Taxonomy Mapping

Analysis dimensions map to taxonomy types as guidance. The analysis session
decides which snippets to produce based on what it finds — this mapping is not
a fixed checklist.

| Analysis Dimension                             | Taxonomy Type | Snippet ID Pattern                                               |
| ---------------------------------------------- | ------------- | ---------------------------------------------------------------- |
| Bounded context contract                       | `spec`        | `local/projects/{project}/spec/domain/{context}`                 |
| User-visible product capability                | `spec`        | `local/projects/{project}/spec/feature/{context}/{concept-name}` |
| Architecture patterns, module organization     | `design`      | `local/projects/{project}/design/{slug}`                         |
| Naming conventions, code style, error handling | `policy`      | `local/projects/{project}/policy/{slug}`                         |
| Dependency inventory, entry points, config     | `spec`        | `local/projects/{project}/spec/{slug}`                           |
| Test strategy, coverage model                  | `design`      | `local/projects/{project}/design/{slug}`                         |
| Build/deploy pipeline                          | `spec`        | `local/projects/{project}/spec/{slug}`                           |
| Operational procedures                         | `procedure`   | `local/projects/{project}/procedure/{slug}`                      |

### Snippet ID Conventions

Generated snippet IDs follow these supported shapes:

- `local/projects/{project}/{taxonomy}/{slug}` for flat project snippets.
- `local/projects/{project}/spec/domain/{context}` for bounded-context domain specs.
- `local/projects/{project}/spec/feature/{context}/{concept-name}` for Category A feature specs.

Where:

- `{project}` is the analyzed project's declared slug; every generated ID
  carries it, and the ID is derived from the snippet's path under `docs/local/`
  (`general/spec/snippet-authoring-schema`).
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
  `docs/local/`.

Reserved snippet IDs (standard set, used as applicable):

```
projects/{project}/design/architecture
projects/{project}/design/test-strategy
projects/{project}/policy/conventions
projects/{project}/spec/dependencies
projects/{project}/spec/entry-points
projects/{project}/spec/build-deploy
projects/{project}/spec/configuration
```

### File Placement

Generated snippets are placed under `docs/local/` following the taxonomy
directory structure:

```
docs/local/
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
description: '{concise description of what this snippet documents}'
generated_by: 'telec-init'
generated_at: '{ISO8601 timestamp}'
---
```

Required fields: `description`, `generated_by`, `generated_at`. Classification
(`id`, `type`, `scope`, `domain`) is derived from the snippet's path and never
authored (`general/spec/snippet-authoring-schema`).

- `generated_by: telec-init` marks the snippet as auto-generated.
- `generated_at` records when the snippet was last generated or refreshed.
- Generated snippets describe current behavior; absence of `delivered_by`
  is the current-state signal. Design-delivery snippets that describe intended
  future state carry `delivered_by: [<owning-slug>]`; analysis does not
  generate those.
- Enrichment-generated snippets live in the project's `docs/local/`, so their
  derived `scope` is always `project`.

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
7. **Diff-scoped re-analysis.** When `.telec-init-meta.yaml` records a
   `last_analyzed_commit`, re-analysis is scoped to the files changed in
   `git diff <last_analyzed_commit>..HEAD`; snippets whose source areas are
   unchanged are left untouched. Absent that commit, the analysis covers the
   full tree.

### Agent Bootstrap Content

The enrichment writer's behavior is governed by the AGENTS.master.md decision
in `sdlc/procedure/project-analysis` (Step 15). The four
normal cases plus the anomaly:

- **Case 1 — `AGENTS.master.md` exists.** The existing artifact source is
  authoritative. The enrichment writer does not modify it.
- **Case 2 — Hand-authored `AGENTS.md` exists, no master.** The enrichment
  writer promotes it: the existing `AGENTS.md` content is moved into a new
  `AGENTS.master.md`. Subsequent artifact distribution regenerates `AGENTS.md`
  (possibly with baseline additions) and nothing else. A `CLAUDE.md` in this
  case is absent or only imports `AGENTS.md`; distribution deletes it only when
  it is untracked and holds nothing but that import.

- **Case 3 — Substantive standalone `CLAUDE.md`, no `AGENTS.md`.** The
  enrichment writer does not create a master. A substantive standalone
  `CLAUDE.md` is a deliberate Claude-Code-only signal. Promotion is possible
  only as an explicit human-driven step.
- **Case 4 (greenfield) — none of the above.** The enrichment writer generates
  a minimal project-specific `AGENTS.master.md` (tech stack, key directories,
  primary conventions). Normal artifact inflation then produces `AGENTS.md` at
  sync time.

**Anomaly — both substantive `AGENTS.md` and substantive `CLAUDE.md`.** Claude
Code loads both files into the same session, so two authored instruction
sources compete. The enrichment writer halts and flags the conflict for human
inspection. It does not auto-promote: which file is authoritative, and whether
the `CLAUDE.md` content moves into the master, is the human's call.

### Validation Contract

The enrichment writer validates all output before persistence:

- Snippet IDs must match one of the supported flat or nested project ID shapes.
- File destinations must resolve to paths under `docs/local/`.
- Frontmatter must contain all required fields.
- Unknown or unsafe snippet IDs (those that would escape `docs/local/`) are
  rejected before any file write.

### Metadata File

The enrichment writer persists `.telec-init-meta.yaml` in the project root:

```yaml
last_analyzed_at: '2024-01-15T10:30:00Z'
last_analyzed_commit: '3f9a1c2'
analyzed_by: telec-init
files_analyzed: 42
snippets_generated:
  - projects/{project}/design/architecture
  - projects/{project}/policy/conventions
  - projects/{project}/spec/dependencies
snippets_preserved:
  - projects/{project}/spec/entry-points
```

This file is read during re-analysis to inform merge decisions and is updated
after each enrichment run.

`last_analyzed_commit` records the HEAD commit the run analyzed; the next run
diffs against it to scope enrichment to changed files.
