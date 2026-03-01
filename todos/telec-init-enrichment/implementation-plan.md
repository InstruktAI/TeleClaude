# Implementation Plan: telec-init-enrichment

## Overview

Extend `telec init` with an AI-driven project analysis and documentation scaffolding
phase. The implementation adds three components: (1) an authorized author guidance doc
snippet that teaches the AI how to analyze projects, (2) an analysis session launcher
integrated into the init flow, and (3) a scaffolding module that turns analysis output
into valid doc snippets. The existing plumbing (hooks, sync, watchers) is untouched.

## Phase 1: Authorized Author Guidance

### Task 1.1: Create the analysis guidance doc snippet

**File(s):** `docs/global/procedure/project-analysis.md`

- [ ] Write a procedure snippet that guides the AI during project analysis
- [ ] Define per-language/framework analysis checklists (Python, TypeScript/Node,
      Go, Rust, generic)
- [ ] Define architecture pattern recognition heuristics
- [ ] Define convention inference rules (from git history, file structure, test patterns)
- [ ] Define snippet output templates — what each generated snippet should contain
- [ ] Define sampling strategy for large codebases (file count thresholds, directory
      prioritization)
- [ ] Define the decision boundary: when to infer vs. when to leave a placeholder
      for human input
- [ ] Include `id`, `description`, `type: procedure`, `scope: general`,
      `visibility: internal` frontmatter

### Task 1.2: Create the scaffolding schema definition

**File(s):** `docs/global/spec/init-scaffolding.md`

- [ ] Define the set of doc snippets the analysis produces and their IDs:
      - `project/init/architecture` — architecture overview
      - `project/init/conventions` — coding conventions and patterns
      - `project/init/dependencies` — dependency inventory and roles
      - `project/init/entry-points` — entry points and routing
      - `project/init/testing` — test patterns and verification model
      - `project/init/build-deploy` — build and deployment model
- [ ] Define frontmatter template for each generated snippet
- [ ] Define the metadata marker for auto-generated snippets (frontmatter field:
      `generated_by: telec-init`, `generated_at: <ISO8601>`)
- [ ] Define merge rules for re-analysis: update auto-generated sections, preserve
      human-authored sections

---

## Phase 2: Analysis Session Infrastructure

### Task 2.1: Add enrichment session launcher to init flow

**File(s):** `teleclaude/project_setup/init_flow.py`

- [ ] After existing plumbing steps, detect if enrichment should run:
      - First init (no `docs/project/init/` directory): prompt user
      - Re-init (directory exists): offer refresh or skip
- [ ] Use `telec sessions run` to launch the analysis session with the
      `/telec-init-analyze` command (see Task 2.3)
- [ ] Pass project root path as argument
- [ ] Print status message: "Analyzing project structure..." with session info
- [ ] Handle user declining enrichment gracefully (skip, continue init as normal)

### Task 2.2: Create the analysis output writer module

**File(s):** `teleclaude/project_setup/enrichment.py`

- [ ] `write_snippet(project_root, snippet_id, content, metadata)` — writes a doc
      snippet with correct frontmatter to `docs/project/init/<name>.md`
- [ ] `read_existing_snippets(project_root)` — reads current auto-generated snippets
      and returns their content for merge decisions
- [ ] `merge_snippet(existing, generated)` — preserves human-authored sections,
      updates auto-generated sections based on metadata markers
- [ ] `ensure_init_directory(project_root)` — creates `docs/project/init/` if missing
- [ ] All generated files use the snippet authoring schema (frontmatter + body)

### Task 2.3: Create the analysis agent command

**File(s):** `agents/skills/telec-init-analyze.md` (or equivalent command artifact)

- [ ] Define the agent command that runs during the analysis session
- [ ] Command loads the authorized author guidance (Task 1.1)
- [ ] Command reads the codebase using the guidance's analysis checklist
- [ ] Command produces structured analysis output
- [ ] Command calls the enrichment writer (Task 2.2) to create doc snippets
- [ ] Command generates initial `AGENTS.md` baseline content for the project
      (create if absent; skip with log message if AGENTS.md already exists)
- [ ] Command commits generated snippets with a clear commit message
- [ ] Command runs `telec sync --validate-only` to verify generated snippets
- [ ] Session ends cleanly after completion

### Task 2.4: Verify generated snippets appear in the index

**File(s):** `teleclaude/docs_index.py` (verification only — no code change expected)

**Note:** `iter_snippet_roots()` at `docs_index.py:372` already scans
`project_root / "docs" / "project"`. Snippets under `docs/project/init/` will be
auto-discovered. This task is verification-only.

- [ ] Confirm `docs/project/init/` snippets are picked up by existing index build
- [ ] Verify `telec docs index` shows generated snippets after enrichment

---

## Phase 3: Idempotency and Re-analysis

### Task 3.1: Implement re-analysis detection and merge

**File(s):** `teleclaude/project_setup/enrichment.py`, `teleclaude/project_setup/init_flow.py`

- [ ] On re-init, detect existing auto-generated snippets via `generated_by` metadata
- [ ] Compare existing snippet content with new analysis
- [ ] Apply merge rules: update auto-generated sections, preserve human edits
- [ ] Log what was updated vs. preserved
- [ ] Commit only changed files

### Task 3.2: Add analysis metadata tracking

**File(s):** `teleclaude/project_setup/enrichment.py`

- [ ] Write `docs/project/init/.analysis-meta.yaml` after each analysis:
      ```yaml
      last_analyzed_at: <ISO8601>
      analyzed_by: telec-init
      files_analyzed: <count>
      snippets_generated: [<snippet_ids>]
      snippets_preserved: [<snippet_ids>]  # human-modified, not overwritten
      ```
- [ ] Read this file during re-analysis to inform merge decisions

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Unit test: `enrichment.write_snippet()` produces valid frontmatter
- [ ] Unit test: `enrichment.merge_snippet()` preserves human sections
- [ ] Unit test: `enrichment.read_existing_snippets()` detects auto-generated markers
- [ ] Integration test: `init_project()` with enrichment produces expected snippets
      in `docs/project/init/`
- [ ] Integration test: generated snippets pass `telec sync --validate-only`
- [ ] Integration test: `telec docs index` includes generated snippets
- [ ] Integration test: re-init merges rather than duplicates

### Task 4.2: Quality Checks

- [ ] Run `make lint`
- [ ] Run `make test`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Manual test: run `telec init` on a sample project, verify snippet quality

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
- [ ] Deferred: event emission during init (depends on `event-envelope-schema`)
- [ ] Deferred: mesh registration during init (depends on `mesh-architecture`)
