# DOR Report: new-bug-key-in-todos-pane

## Gate Assessment

**Date:** 2026-02-22
**Assessor:** Claude (formal DOR gate)
**Verdict:** PASS (10/10)

### Summary

Six requirements covering: dependency tree rendering fix (build from `after` graph, not list order), unscoped file viewer (filepath-based, not slug-scoped), `roadmap.yaml` as first tree entry, and bug creation (`b` key + CLI command). Implementation plan has 7 tasks with verified source references.

### DOR Gate Assessment

| Gate                  | Score | Notes                                                                                                                                                    |
| --------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Intent & Success   | PASS  | 6 in-scope items, 14 testable success criteria. Problem and outcome explicit.                                                                            |
| 2. Scope & Size       | PASS  | 4 files touched. Tasks 1-3 tightly coupled (same file, enabling chain). Tasks 4-6 small and independent. Fits one session. No split needed.              |
| 3. Verification       | PASS  | Each task has manual verification. Cross-cutting validation in Task 7. Tree ordering test: reorder roadmap.yaml → structure unchanged.                   |
| 4. Approach Known     | PASS  | DFS from `after` graph is standard. Filepath generalization is a signature change. All source references verified. `_find_parent_todo` safe for slug="". |
| 5. Research           | N/A   | No third-party dependencies.                                                                                                                             |
| 6. Dependencies       | PASS  | `bug-delivery-service` in roadmap.yaml. Tasks 1-3 have no deps. Tasks 4-6 explicitly marked as prerequisite-gated; builder can defer if dep not ready.   |
| 7. Integration Safety | PASS  | Additive changes. Tree algorithm replaces old in same function. No existing behavior removed. All `_editor_command` callers updated in same task.        |
| 8. Tooling Impact     | N/A   | No tooling changes.                                                                                                                                      |

### Scope Splitting Decision

**No split.** Tasks 1-3 (tree fix, viewer, roadmap entry) are tightly coupled and belong together. Tasks 4-6 (bug creation) are small additions to the same files. The `bug-delivery-service` dependency is handled at roadmap level — if the dep isn't ready at build time, the builder implements tasks 1-3 and defers 4-6 as documented deferrals. This is cleaner than maintaining two separate todos that touch the same code.

### Source Verification (gate spot-checks)

| Reference                     | File                     | Gate Verified                                                |
| ----------------------------- | ------------------------ | ------------------------------------------------------------ |
| `_editor_command(slug, file)` | `preparation.py:335`     | Confirmed hardcoded `todos/{slug}/{filename}`                |
| `TodoFileRow.__init__`        | `todo_file_row.py:35-47` | Confirmed: slug + filename, no filepath                      |
| `action_activate` file path   | `preparation.py:435-436` | Confirmed: uses `file_row.slug` + `file_row.filename`        |
| `_find_parent_todo` slug=""   | `preparation.py:359`     | Safe: no TodoRow has empty slug, returns None for standalone |
| `action_collapse` None parent | `preparation.py:412`     | Safe: checks `if parent:` before collapsing                  |

### Blockers

None.

### Score Rationale

10/10 — Every behavioral change has automated verification specified upfront:

- **Tree building:** 11 unit tests in `test_prep_tree_builder.py` covering roots, parent-child, order irrelevance, unresolvable deps, multi-level nesting, sibling ordering, multi-parent, circular deps, is_last, and tree_lines continuation.
- **File viewer:** 5 unit tests in `test_prep_file_viewer.py` covering editor command with absolute path, view flag, theme flag, standalone file row parent isolation (slug=""), and slug-scoped parent lookup.
- All logic extracted as pure functions for testability without TUI widgets.
