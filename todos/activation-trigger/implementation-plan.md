# activation-trigger — Implementation Plan

## Overview

Two coherent flows delivered atomically: (1) collapse the dual warn/error validation
severity into a single error pipeline, and (2) add the `activation_trigger` frontmatter
field flowing through validation → distribution → docs. The high detail in requirements
and the mechanical nature of most changes (28 `_warn`→`_error` renames, 11 frontmatter
additions) make this a single builder session.

## Task Status

- [x] Task 1: Unify validation severity (R1)
- [x] Task 2: Add `activation_trigger` frontmatter validation (R2)
- [x] Task 3: Delete redundant top-level spec file (spec review F-01/F-02)
- [x] Task 4: Render activatable procedures section in AGENTS.md (R3, R4)
- [x] Task 5: Clean baseline-progressive and annotate procedures (R5, R6)
- [x] Task 6: Update skill-authoring procedure (R7)
- [x] Task 7: Delete skill-creator skill (R8)
- [x] Task 8: Document `activation_trigger` in snippet-authoring-schema (R9)

---

## Task 1: Unify validation severity (R1)

### What

Replace the dual `_warn`/`_error` collection in `_models.py` with a single error
pipeline. Remove `_warn()`, `get_warnings()`, and `clear_warnings()` — replace with
`_error()`, `get_errors()`, and `clear_errors()`.

### Why

The warn/error distinction has no semantic value. All findings are errors that block
`telec sync` unless `--warn-only` is set. The dual layer adds surface area (two
collection functions, two retrieval functions, two clear functions) without benefit.
Unifying prevents future call sites from choosing the wrong severity bucket.

### Changes

1. **`teleclaude/resource_validation/_models.py`**
   - Remove `_WARNINGS` list, `_warn()`, `get_warnings()`, `clear_warnings()`.
   - Add `clear_errors()` that clears `_ERRORS`.
   - Keep `_error()`, `get_errors()` unchanged.
   - Update `__all__`: export `_error`, `get_errors`, `clear_errors`; remove
     `_warn`, `get_warnings`, `clear_warnings`.

2. **`teleclaude/resource_validation/_snippet.py`**
   - Replace all 28 `_warn(` calls with `_error(` — mechanical rename.
   - Update import: remove `_warn`, confirm `_error` is already imported.

3. **`teleclaude/resource_validation/__init__.py`**
   - Remove `_warn`, `get_warnings`, `clear_warnings` from imports and `__all__`.
   - Add `clear_errors` to imports and `__all__`.

4. **`teleclaude/sync.py`**
   - Replace `clear_warnings()` import/call with `clear_errors()`.
   - Remove `get_warnings()` import/call and the `warnings` variable.
   - Collapse logic: after validation, `get_errors()` holds all findings.
     The existing `get_errors()` call already collects see-also errors — merge
     the two into one pass. `warn_only` controls whether findings block sync.
   - Rename `_print_warnings` → `_print_findings` (or equivalent). Update the
     heading text from `"Validation warnings:"` to `"Validation findings:"`.
   - Update imports.

5. **Adapt 4 existing tests:**
   - `tests/unit/resource_validation/test__models.py::test_warn_and_error_are_collected_and_clearable`:
     Rewrite to test `_error`/`get_errors`/`clear_errors` unified API.
   - `tests/unit/resource_validation/test__snippet.py::test_warns_for_non_url_source_entries`:
     Switch `clear_warnings()`→`clear_errors()`, `get_warnings()`→`get_errors()`,
     error code stays `third_party_source_invalid`.
   - `tests/unit/test_sync.py::TestPrintWarnings::test_groups_warnings_by_code_and_reason`:
     Replace prose-lock `"Validation warnings: 2"` with behavioral assertion on
     structured data or the renamed function.
   - `tests/unit/project_setup/test_sync.py::test_sync_project_artifacts_prints_warning_when_sync_reports_false`:
     Replace prose-lock `"sync completed with warnings"` with behavioral assertion
     (e.g., assert `sync()` returns `False`).

### Verification

- Remove xfail from `test_unified_severity_spec.py` — all 10 tests GREEN (includes existing tests plus new `test_get_warnings_removed_from_package`).
- All 4 adapted existing tests pass.

---

## Task 2: Add `activation_trigger` frontmatter validation (R2)

### What

Add validation logic in `_snippet.py::validate_snippet()` that checks the
`activation_trigger` frontmatter field: accepted on procedures (non-empty string),
rejected on all other types, rejected for empty/non-string values.

### Why

Without validation, invalid `activation_trigger` values would silently pass through
to the distribution pipeline, producing broken AGENTS.md output or silently missing
entries. Validating at the snippet level catches errors at authoring time.

### Changes

1. **`teleclaude/resource_validation/_snippet.py::validate_snippet()`**
   - After existing frontmatter validation (around line 230), check
     `meta.get("activation_trigger")`.
   - If present and snippet type is not `"procedure"`:
     `_error("snippet_activation_trigger_invalid_type", path=str(path))`.
   - If present on procedure and value is not a `str`:
     `_error("snippet_activation_trigger_invalid_value", path=str(path))`.
   - If present on procedure and value is empty string:
     `_error("snippet_activation_trigger_empty", path=str(path))`.

### Verification

- Remove xfail from `tests/unit/resource_validation/test_activation_trigger_validation_spec.py`
  — all 4 tests GREEN (validation acceptance and rejection scenarios).

---

## Task 3: Delete redundant top-level spec file (spec review F-01/F-02)

### What

Delete `tests/unit/test_activation_trigger_validation_spec.py` and add one test
to `TestWarningAPIRemoved` in `test_unified_severity_spec.py` asserting
package-level absence of `get_warnings`.

### Why

Spec review round 3 identified this file as redundant — it duplicates R1/R2
coverage from the `resource_validation/` spec files and references the non-existent
`sync._run_validate` function. The one unique contribution (package-level
`get_warnings` check) belongs in `test_unified_severity_spec.py`.

### Changes

1. Delete `tests/unit/test_activation_trigger_validation_spec.py`.
2. Add to `TestWarningAPIRemoved` in `test_unified_severity_spec.py`:
   ```python
   def test_get_warnings_removed_from_package(self) -> None:
       import teleclaude.resource_validation as rv
       assert not hasattr(rv, "get_warnings")
   ```

### Verification

- File deleted.
- New test GREEN alongside other `TestWarningAPIRemoved` tests.

---

## Task 4: Render activatable procedures section in AGENTS.md (R3, R4)

### What

Modify `scripts/distribute.py::_render_progressive_index()` to exclude procedures
with `activation_trigger` from the baseline index and render a dedicated
"Activatable Procedures" section appended after it.

### Why

This is the core progressive disclosure mechanism. Procedures with
`activation_trigger` need a compact, scannable section in AGENTS.md that gives
agents recognition-level awareness without loading full content. Baseline index
exclusion prevents duplication.

### Changes

1. **`scripts/distribute.py::_render_progressive_index()`**
   - While iterating refs, read `activation_trigger` from each snippet's
     frontmatter alongside `id` and `description`.
   - If `activation_trigger` is a non-empty string on a procedure: collect
     `(snippet_id, activation_trigger)` into an `activatable` list; skip adding
     to `entries`.
   - After the baseline index block, if `activatable` is non-empty, sort by
     snippet ID and append:

     ```markdown
     ## Activatable Procedures — load via `telec docs get <id>` before acting

     - `snippet/id` — trigger text
     ```

### Verification

- Remove xfail from `test_activation_trigger_distribution_spec.py` — all 7 tests GREEN:
  - `test_procedure_with_activation_trigger_excluded_from_baseline` (R4)
  - `test_all_trigger_procedures_excluded_leaves_remaining_entries` (R4)
  - `test_activatable_section_rendered_for_trigger_procedures` (R3)
  - `test_activatable_section_appears_after_baseline_index` (R3)
  - `test_activatable_entries_are_sorted` (R3)
  - `test_activatable_section_includes_docs_get_header` (R3)
  - `test_activatable_entry_shows_trigger_text` (R3)

---

## Task 5: Clean baseline-progressive and annotate procedures (R5, R6)

### What

1. Remove 6 procedure references from `docs/global/baseline-progressive.md`.
2. Add `activation_trigger` to frontmatter of 11 procedure snippet files.

### Why

R5: The 6 procedures will appear in the activatable section; keeping them in
baseline-progressive duplicates them.

R6: The `activation_trigger` field drives the new section — without it,
procedures won't appear in the activatable output.

### Changes

1. **`docs/global/baseline-progressive.md`** — remove lines referencing:
   - `general/procedure/agent-artifact-authoring`
   - `general/procedure/doc-snippet-authoring`
   - `general/procedure/peer-discussion`
   - `general/procedure/memory-management`
   - `general/procedure/brainstorming`
   - `software-development/procedure/debugging`

2. **11 procedure files** (source in `docs/global/`, deployed to `~/.teleclaude/docs/`)
   — add `activation_trigger` field to YAML frontmatter after `description`:

   | File                                                                  | `activation_trigger`                                                                |
   | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
   | `general/procedure/brainstorming.md`                                  | Use when the user wants to refine an idea before implementation                     |
   | `software-development/procedure/debugging.md`                         | Use when you encounter a bug, test failure, or unexpected behavior                  |
   | `general/procedure/peer-discussion.md`                                | Use when a complex topic would benefit from two agents covering it together         |
   | `general/procedure/youtube-research.md`                               | Use when user needs YouTube video search, channel research, or transcripts          |
   | `general/procedure/git-repo-ingestion.md`                             | Use when you need to analyze an external Git repository                             |
   | `general/procedure/firecrawl-web-scraping.md`                         | Use when web search fails and you need to scrape JavaScript-rendered content        |
   | `general/procedure/memory-management.md`                              | Use when you encounter a durable user preference, friction, or relationship context |
   | `software-development/procedure/research/tech-stack-documentation.md` | Use when researching a library or framework not yet in consolidated docs            |
   | `general/procedure/doc-snippet-authoring.md`                          | Use when creating or updating documentation snippets                                |
   | `general/procedure/agent-artifact-authoring.md`                       | Use when creating or updating agent artifacts                                       |
   | `software-development/procedure/research/third-party-research.md`     | Use when researching third-party documentation and consolidating findings           |

### Verification

- Remove xfail from `test_activation_trigger_content_spec.py` for R5/R6:
  - Parametrized tests for R5 (6 procedures removed) and R6 (11 procedures with activation_trigger) GREEN.
  - Total of 8 tests in this file, all GREEN.

---

## Task 6: Update skill-authoring procedure (R7)

### What

Update `docs/global/general/procedure/skill-authoring.md` (and deployed copy) to
reflect that `activation_trigger` is the primary discovery mechanism for procedural
capabilities.

### Why

Step 1 currently redirects to "add it to the appropriate baseline index." Post this
change, the redirect should explain that procedural knowledge uses `activation_trigger`
for progressive disclosure in AGENTS.md — skills exist only for executable scripts.

### Changes

1. **`docs/global/general/procedure/skill-authoring.md`** — update step 1:
   - Replace "add it to the appropriate baseline index so it is progressively
     disclosed on load" with guidance to add `activation_trigger` to the
     procedure's frontmatter for progressive disclosure in AGENTS.md.
   - State explicitly: procedural capabilities use `activation_trigger` for
     progressive disclosure, not skills; skill creation is gated exclusively
     on carrying executable scripts.

### Verification

- Remove xfail from `TestSkillAuthoringProcedureUpdate` — both tests GREEN.

---

## Task 7: Delete skill-creator skill (R8)

### What

Delete `agents/skills/skill-creator/` directory.

### Why

Superseded by `activation_trigger` on the agent-artifact-authoring procedure and
the skill-authoring procedure's gate logic. No executable scripts to preserve.

### Changes

1. Delete `agents/skills/skill-creator/` (contains `SKILL.md` and `scripts/`).

### Verification

- Remove xfail from `TestSkillCreatorDeletion` — test GREEN.
- `telec sync` succeeds without it.

---

## Task 8: Document `activation_trigger` in snippet-authoring-schema (R9)

### What

Add `activation_trigger` to the "Frontmatter (optional)" section of the
snippet-authoring-schema spec.

### Why

The schema spec is the single source of truth for snippet frontmatter. Authors
need to know the field exists, its constraints, and its effect.

### Changes

1. **`docs/global/general/spec/snippet-authoring-schema.md`** (and deployed copy)
   - Add to "Frontmatter (optional)" list:
     ```
     - `activation_trigger` — (procedures only) non-empty string describing when
       to activate the procedure. Appears in the "Activatable Procedures" section
       of generated AGENTS.md for progressive disclosure. Validation rejects this
       field on non-procedure snippet types.
     ```

### Verification

- Remove xfail from `TestSchemaDocumentation` — all 3 tests GREEN.

---

## Task Ordering

```
Task 1 (R1: severity) → Task 2 (R2: validation) → Task 3 (F-01/F-02 cleanup)
                                                  → Task 4 (R3/R4: distribution)
                                                  → Task 5 (R5/R6: content)
                                                  → Task 6 (R7: skill-authoring)
                                                  → Task 7 (R8: skill-creator)
                                                  → Task 8 (R9: schema docs)
```

Tasks 1→2 are sequential (R2 tests import unified API). Tasks 3-8 depend on
Task 1 completing but are otherwise independent. Listed sequentially for a
single builder session.

## End-to-end Verification

After all tasks:

1. All xfail markers removed from the 4 remaining spec files.
2. `tests/unit/test_activation_trigger_validation_spec.py` deleted.
3. Pre-commit hooks pass (lint, type-check, all tests).
4. `telec sync --validate-only` passes.
5. `telec sync` produces AGENTS.md with "Activatable Procedures" section
   listing 11 procedures with correct trigger text.
6. Baseline index no longer contains the 6 removed procedures.

## Demo Validation

See `demo.md` for full end-to-end validation playbook covering:

- Validation passes with activation_trigger on all 11 procedures
- AGENTS.md contains Activatable Procedures section with 11 sorted entries
- 6 procedures removed from baseline index
- skill-creator directory deleted
- All spec tests pass with no xfail markers
