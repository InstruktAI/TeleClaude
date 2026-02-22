# DOR Report: new-bug-key-in-todos-pane

## Gate Assessment

**Date:** 2026-02-22
**Assessor:** Claude (formal DOR gate)
**Verdict:** PASS (9/10)

### Summary

This todo adds a `b` keybinding to the TUI todos pane and a `telec bugs create` CLI command. Both create a bug skeleton (`bug.md` + `state.yaml`) and the TUI variant opens `bug.md` in the editor.

### Artifact Quality

| Artifact                 | Status   | Notes                                                         |
| ------------------------ | -------- | ------------------------------------------------------------- |
| `input.md`               | Present  | Brain dump decoded into clear requirements                    |
| `requirements.md`        | Complete | Clear goal, 8 testable success criteria, explicit constraints |
| `implementation-plan.md` | Complete | 4 tasks, mirrors existing codebase patterns exactly           |

### DOR Gate Assessment

| Gate                  | Score | Notes                                                                                                                                                     |
| --------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Intent & Success   | PASS  | Clear problem statement. 8 explicit, testable success criteria covering TUI flow, CLI flow, error handling, and lint                                      |
| 2. Scope & Size       | PASS  | 3 small code changes (new modal, keybinding+action, CLI subcommand) + validation. Single session easily                                                   |
| 3. Verification       | PASS  | Manual TUI + CLI tests, edge cases, lint, existing test suite. No new unit tests required (UI-driven)                                                     |
| 4. Approach Known     | PASS  | Direct mirror of `n` -> `action_new_todo()` -> `CreateTodoModal` -> scaffold -> `DocEditRequest` pattern. All four reference points verified in source    |
| 5. Research           | N/A   | No third-party dependencies                                                                                                                               |
| 6. Dependencies       | PASS  | Hard dep on `bug-delivery-service` (DOR passed, score 8, phase: ready). Provides `create_bug_skeleton()`, `bug.md` template, and `telec bugs` CLI surface |
| 7. Integration Safety | PASS  | Purely additive: new `b` keybinding (no collision), new `CreateBugModal` class, new `create` subcommand under `bugs`. No changes to existing behavior     |
| 8. Tooling Impact     | N/A   | No tooling or scaffolding changes                                                                                                                         |

### Source Code Verification

Spot-checked the following implementation plan references against actual source:

| Reference                        | File                  | Verified                                                    |
| -------------------------------- | --------------------- | ----------------------------------------------------------- |
| `BINDINGS` list pattern          | `preparation.py:47`   | Matches -- list of tuples with (key, action, label)         |
| `action_new_todo()` flow         | `preparation.py:463`  | Matches -- modal callback -> scaffold -> DocEditRequest     |
| `CreateTodoModal` structure      | `modals.py:338`       | Matches -- ~48 lines, slug input, SLUG_PATTERN validation   |
| `create_todo_skeleton` signature | `todo_scaffold.py:44` | Matches -- `(project_root: Path, slug: str, *, after=None)` |
| `DocEditRequest` signature       | `messages.py:203`     | Matches -- `(doc_id, command, title)`                       |
| `_editor_command` helper         | `preparation.py:335`  | Available -- builds absolute path editor command            |
| `_slug_to_project_path` dict     | `preparation.py:68`   | Available -- maps slugs to project paths                    |

### Dependency Analysis

**Hard dependency on `bug-delivery-service`** (DOR score 8, phase: ready):

| What this todo needs              | Where it comes from | bug-delivery-service task |
| --------------------------------- | ------------------- | ------------------------- |
| `create_bug_skeleton()` function  | `todo_scaffold.py`  | Task 2                    |
| `templates/todos/bug.md` template | `templates/todos/`  | Task 1                    |
| `telec bugs` CLI surface + router | `telec.py`          | Task 3                    |

The `create_bug_skeleton()` signature will be `(project_root, slug, description, *, reporter="manual", session_id="none")` -- positional `description` parameter matches the planned call with `description=""`.

The `telec bugs` router will follow the same `_handle_bugs()` dispatch pattern as `_handle_todo()` and `_handle_roadmap()` (verified in `telec.py`). Adding `create` as a subcommand is straightforward.

### Assumptions (validated)

1. `create_bug_skeleton()` accepts `description=""` for manual creation. **Validated** against bug-delivery-service implementation plan Task 2 signature.
2. The `telec bugs` command surface uses a router pattern allowing new subcommands. **Validated** against existing `_handle_todo()` / `_handle_roadmap()` patterns in `telec.py`.
3. `CreateBugModal` is a simple copy of `CreateTodoModal` with different title text. **Validated** -- `CreateTodoModal` is ~48 lines, duplication cost is minimal, and the title distinction is user-facing.

### Open Questions

None.

### Blockers

None remaining. The dependency on `bug-delivery-service` is handled by roadmap ordering (`after: [bug-delivery-service]`).
