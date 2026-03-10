# Implementation Plan: telec-init-enrichment

## Atomicity Decision

**ATOMIC — proceed.** This is one coherent behavior change: `telec init` remains the
plumbing entrypoint, then optionally boots an AI analysis pass that scaffolds durable
project docs and baseline agent context. Splitting the guidance docs, init-flow wiring,
writer/merge logic, manifest registration, and validation into separate todos would
create half-working states with no independent ship value.

## Execution Rules

- [ ] Any task that changes behavior starts with the named failing test(s) before
      production code.
- [ ] Use targeted tests while iterating; use the normal pre-commit hook path before
      commit, and only escalate to broader suites if targeted checks or hooks show a
      wider regression risk.
- [ ] Reuse existing TeleClaude surfaces. Do not introduce a parallel project-catalog
      or release-channel config mechanism.

## Overview

Extend `telec init` with an AI-driven project analysis and documentation scaffolding
phase. The implementation adds four linked pieces:

1. Authorized-author guidance that teaches the analysis session what to inspect.
2. A schema contract for the snippets and baseline artifacts the session emits.
3. Init-flow orchestration plus a writer/merge module that turns analysis output into
   valid project snippets and safe re-analysis updates.
4. Validation and demo coverage proving generated snippets are discoverable, specific,
   and safe to refresh.

The existing plumbing (hooks, sync, watchers) remains the base behavior and must stay
regression-free when enrichment is declined.

## Phase 1: Guidance Contracts

### Task 1.1: Create the analysis guidance doc snippet

**File(s):** `docs/global/software-development/procedure/project-analysis.md`

- [ ] Write a procedure snippet that guides the AI during project analysis.
- [ ] Define per-language/framework analysis checklists (Python, TypeScript/Node,
      Go, Rust, generic) that explicitly cover:
      - Language/framework detection
      - Entry points and route/handler mapping
      - Architecture pattern recognition
      - Test patterns and verification model
      - Dependency inventory and role classification
      - Build/deploy model
      - Configuration structure (config files, env vars, feature flags)
      - Git history patterns
      - Existing documentation inventory
- [ ] Define convention inference rules from git history, file structure, and test
      patterns.
- [ ] Define sampling strategy for large codebases (file count thresholds, directory
      prioritization, fallbacks when the context window is tight).
- [ ] Define the decision boundary: when to infer, when to preserve ambiguity, and
      when to leave a placeholder for human follow-up.
- [ ] Include snippet-output guidance for the generated project snippets and the
      project-local `AGENTS.md` bootstrap content.
- [ ] Include valid frontmatter with `id`, `description`, `type: procedure`, and
      `scope`.

**Why:** The guidance snippet is the contract between `telec init` and the analysis
session. It has to encode every required discovery dimension up front so the session
does not rely on ad hoc prompting.

**Verification:** `telec docs get software-development/procedure/project-analysis`
returns the snippet, and the analysis session transcript or test double can prove this
snippet is referenced explicitly.

---

### Task 1.2: Create the scaffolding schema definition

**File(s):** `docs/global/software-development/spec/init-scaffolding.md`

- [ ] Define the discovery-to-taxonomy mapping: which analysis dimensions map to
      which taxonomy types (`principle`, `concept`, `policy`, `procedure`, `design`,
      `spec`). The mapping is guidance, not a fixed list — the analysis session
      decides which snippets to produce based on what it finds in the codebase.
- [ ] Define naming conventions for generated snippet IDs under `project/`.
- [ ] Define the expected file placement per taxonomy type under `docs/project/`.
- [ ] Define the frontmatter template for generated snippets, including
      `generated_by: telec-init` and `generated_at: <ISO8601>`.
- [ ] Define merge rules for re-analysis: update auto-generated sections, preserve
      human-authored sections, and keep the operation idempotent.
- [ ] Define how generated `AGENTS.md` content coexists with existing agent artifact
      rules (`AGENTS.master.md` inflation, `CLAUDE.md` companion behavior, and
      skip-if-present handling for plain `AGENTS.md`).

**Why:** The writer module and analysis command need one schema source of truth for
IDs, metadata, file placement, and merge semantics.

**Verification:** `telec docs get software-development/spec/init-scaffolding`
returns the snippet, and writer tests validate emitted frontmatter and IDs against
this contract.

## Phase 2: Init Flow and Analysis Execution

### Task 2.1: Add enrichment prompting and session launch to `telec init`

**File(s):** `teleclaude/project_setup/init_flow.py`, `teleclaude/cli/telec.py`,
`docs/project/spec/telec-cli-surface.md`, `README.md`,
`tests/unit/test_project_setup_init_flow.py`, `tests/integration/test_telec_cli_commands.py`,
`tests/integration/test_contracts.py`

- [ ] Start with failing tests for:
      - First init prompts for enrichment when no `generated_by: telec-init` snippets exist
      - Re-init offers refresh/skip when auto-generated snippets already exist
      - Declining enrichment preserves the current plumbing-only behavior
      - Existing hook/sync/watch order remains unchanged
- [ ] After the existing plumbing steps complete, detect whether enrichment should run.
- [ ] On first init, prompt to run enrichment or skip.
- [ ] On re-init, offer refresh or skip.
- [ ] Launch `telec sessions run --command /telec-init-analyze --project <root>`
      and print a status message with enough session context to follow the run.
- [ ] Handle a declined enrichment path gracefully and continue with normal init
      completion output.
- [ ] Update `telec init` help/usage text so the enrichment option is visible in the
      user-facing command description.
- [ ] Update the user-facing command docs that mirror `telec init` behavior
      (`docs/project/spec/telec-cli-surface.md` and `README.md`) so the documented
      setup flow matches the new optional enrichment step and any release-channel
      choice the command actually exposes.

**Why:** Optional enrichment is user-visible behavior layered on top of the existing
init contract. The prompt path, session launch, help text, and mirrored user-facing
docs all need to reflect the new behavior without destabilizing the existing plumbing.

**Verification:** Targeted init-flow, CLI, and contract tests pass, `telec init --help`
shows that init includes an optional enrichment step, and the README / CLI surface
spec describe the same behavior.

---

### Task 2.2: Create the enrichment writer and merge module

**File(s):** `teleclaude/project_setup/enrichment.py`,
`tests/unit/project_setup/test_enrichment.py`

- [ ] Start with failing tests for snippet writing, directory creation, existing
      snippet detection, merge preservation, metadata persistence, and rejection of
      unknown or unsafe snippet IDs.
- [ ] Implement `write_snippet(project_root, snippet_id, content, metadata)` so it
      writes schema-valid snippets under `docs/project/`.
- [ ] Implement `read_existing_snippets(project_root)` so re-analysis can inspect
      current generated snippets and metadata markers.
- [ ] Implement `merge_snippet(existing, generated)` so human-authored sections
      survive refresh runs.
- [ ] Implement `ensure_taxonomy_directories(project_root, snippet_ids)` for the
      required `design/`, `policy/`, and `spec/` directories.
- [ ] Validate analysis output against the canonical snippet ID set and normalized
      `docs/project/` destinations before any file write so the AI session cannot
      create unexpected files or escape the taxonomy contract.
- [ ] Write and read `.telec-init-meta.yaml` with timestamps, counts, generated
      snippet IDs, and preserved snippet IDs.

**Why:** The writer/merge module is the narrow boundary between AI analysis output and
durable repo artifacts. Keeping that logic isolated makes idempotency and validation
testable.

**Verification:** Targeted enrichment tests pass and generated files land under the
correct taxonomy directories with valid frontmatter and merge markers, while invalid
snippet IDs are rejected before persistence.

---

### Task 2.3: Create the analysis slash command artifact

**File(s):** `agents/commands/telec-init-analyze.md`

- [ ] Define the slash command invoked by `/telec-init-analyze`.
- [ ] Load the guidance and scaffolding snippets from Tasks 1.1 and 1.2 via
      explicit required reads.
- [ ] Instruct the session to inspect the repo with the guidance checklist and emit
      structured output that the enrichment writer can persist.
- [ ] Instruct the session to generate initial project-specific `AGENTS.md` content
      only when `AGENTS.md` is absent; if an artifact source file already exists, keep
      normal artifact-governance behavior instead of writing around it.
- [ ] Instruct the session to commit generated snippet changes with a clear message,
      run `telec sync --validate-only`, and finish cleanly.
- [ ] Make the required-read references observable in the transcript so tests can
      prove the guidance contract was actually used.

**Why:** The slash command is the executable contract for the analysis session. It
must reference the guidance explicitly, define artifact output expectations, and end
with observable success criteria.

**Verification:** A transcript assertion or command test double shows the required
reads for the guidance/scaffolding snippets, `telec sync --validate-only` succeeds,
and the session does not remain active after artifact generation.

---

### Task 2.4: Lock index discovery and docs retrieval behavior

**File(s):** `teleclaude/docs_index.py`, `tests/unit/test_docs_index.py`

- [ ] Add or update a targeted regression test that proves snippets under
      `docs/project/` are still discovered by `iter_snippet_roots()`.
- [ ] Verify `telec docs index` lists the generated snippets after enrichment.
- [ ] Verify `telec docs get <generated-snippet-id>` returns non-empty,
      project-specific content rather than boilerplate placeholders.

**Why:** Index inclusion and retrievability are explicit success criteria. The current
code already discovers `docs/project/`, but the plan needs a regression guard so that
future refactors do not silently break enrichment discoverability.

**Verification:** The targeted docs-index test passes, `telec docs index` shows the
new snippet IDs, and `telec docs get` returns project-specific content.

---

### Task 2.5: Preserve local TeleClaude integration surfaces during init

**File(s):** `teleclaude/project_setup/init_flow.py`, `teleclaude/sync.py`,
`teleclaude/project_manifest.py`, `teleclaude/cli/telec.py`,
`tests/unit/test_project_setup_init_flow.py`, `tests/unit/test_telec_sync.py`,
`tests/unit/test_context_selector.py`, `tests/integration/test_telec_cli_commands.py`

- [ ] Start with failing tests proving a first-time `telec init` on a repo without a
      pre-existing `teleclaude.yml` still ends with a live project-manifest entry that
      points at `docs/project/index.yaml`.
- [ ] If manifest registration currently depends on `teleclaude.yml` existing before
      sync begins, adjust the init/sync ordering so first-run projects are registered
      after config creation.
- [ ] Reuse the existing project catalog behavior instead of introducing a parallel
      registration file or init-only manifest path.
- [ ] Reuse the existing deployment config surface. If init exposes a non-default
      release-channel choice, persist it only through `deployment.channel` and
      `deployment.pinned_minor`; otherwise keep the existing defaults unchanged and
      avoid new config keys or YAML sections.

**Why:** The project-catalog requirement is observable behavior, and the current
first-run sync path has an edge case around registering a project after
`teleclaude.yml` is created. Release-channel handling must stay on the existing config
surface so init does not fork deployment behavior.

**Verification:** Targeted sync/init tests pass, `telec projects list` shows the repo
after init, and no new config surface appears beyond the existing deployment fields.

## Phase 3: Idempotency and Re-analysis

### Task 3.1: Implement re-analysis detection and merge behavior

**File(s):** `teleclaude/project_setup/enrichment.py`,
`teleclaude/project_setup/init_flow.py`, `tests/unit/project_setup/test_enrichment.py`

- [ ] Start with failing tests for re-init refresh/skip detection, changed-file-only
      commits, and preservation of human-authored sections.
- [ ] Detect existing auto-generated snippets via `generated_by` metadata.
- [ ] Compare existing snippet content with the new analysis output.
- [ ] Apply the merge rules from Task 1.2 and log what was updated versus preserved.
- [ ] Commit only changed generated files on refresh runs.

**Why:** Idempotency is a core requirement, not a follow-up enhancement. The refresh
path has to be safe before the feature ships.

**Verification:** Targeted re-analysis tests pass; a second run updates snippets
instead of duplicating them and preserves human-authored sections.

---

### Task 3.2: Persist and consume analysis metadata

**File(s):** `teleclaude/project_setup/enrichment.py`,
`tests/unit/project_setup/test_enrichment.py`

- [ ] Start with a failing test that asserts `.telec-init-meta.yaml` is written with
      the expected keys and then reused on re-analysis.
- [ ] Persist:
      ```yaml
      last_analyzed_at: <ISO8601>
      analyzed_by: telec-init
      files_analyzed: <count>
      snippets_generated: [<snippet_ids>]
      snippets_preserved: [<snippet_ids>]
      ```
- [ ] Read the metadata file during re-analysis to inform merge decisions and logs.

**Why:** Explicit metadata makes re-analysis deterministic and auditable instead of
relying on implicit file heuristics alone.

**Verification:** Metadata tests pass and manual inspection shows the file tracking
timestamps, counts, generated snippet IDs, and preserved snippet IDs.

## Phase 4: Validation

### Task 4.1: Targeted tests and transcript checks

- [ ] Unit tests:
      - `write_snippet()` produces valid frontmatter
      - `merge_snippet()` preserves human sections
      - `read_existing_snippets()` detects auto-generated markers
      - first-run init registers the project manifest after config creation
      - init help/prompt copy reflects enrichment
      - the analysis transcript proves the guidance/scaffolding required reads were used
- [ ] Integration tests:
      - `init_project()` with enrichment produces snippets under the correct taxonomy
        directories
      - generated snippets pass `telec sync --validate-only`
      - `telec docs index` includes generated snippets
      - `telec docs get <generated-snippet-id>` returns project-specific non-empty content
      - re-init merges rather than duplicates
      - the enrichment session exits cleanly after generation
      - the CLI surface contract test still passes after the `telec init` docs updates
- [ ] Keep the existing init plumbing regression coverage green so hooks, sync, and
      watchers remain unchanged when enrichment is skipped.

**Why:** These tests map directly to the success criteria and the highest-risk
behavioral regressions.

**Verification:** The targeted unit and integration test files for init, enrichment,
sync, and docs indexing pass locally.

---

### Task 4.2: Quality checks and manual verification

- [ ] Run only the targeted pytest files for the touched init/enrichment/command/index
      paths while developing.
- [ ] Run `telec todo demo validate telec-init-enrichment`.
- [ ] Run the normal pre-commit hook path before commit; if hooks or targeted checks
      expose wider issues, escalate to broader suites.
- [ ] Manual test: run `telec init` on a sample project, accept enrichment, verify
      snippet quality, `telec docs get`, `telec projects list`, and re-init
      preservation.

**Why:** This matches the repository verification policy: targeted checks by default,
demo validation for user-facing behavior, and hooks as the final gate.

**Verification:** Targeted tests, demo validation, and the normal hook path all pass.

## Phase 5: Review Readiness

- [ ] Update `todos/telec-init-enrichment/demo.md` so the executable steps use the
      taxonomy paths under `docs/project/design/`, `docs/project/policy/`, and
      `docs/project/spec/`.
- [ ] Ensure the demo covers `telec docs get`, `telec projects list`, and re-init
      preservation in observable commands.
- [ ] Confirm requirements are reflected in code changes with no silent scope drops.
- [ ] Confirm implementation-plan task checkboxes are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
- [ ] Deferred: event emission during init (depends on `event-envelope-schema`).
- [ ] Deferred: mesh registration during init (depends on `mesh-architecture`).

**Why:** The demo lane is mandatory for user-visible init behavior, and the explicit
deferrals prevent out-of-scope work from being smuggled into build.

**Verification:** `telec todo demo validate telec-init-enrichment` passes and the demo
steps match the implementation surface.
