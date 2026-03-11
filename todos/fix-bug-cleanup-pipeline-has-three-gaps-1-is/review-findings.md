# Review Findings: fix-bug-cleanup-pipeline-has-three-gaps-1-is

## Scope

Bug fix review against `bug.md`. All three gaps verified against the diff.

Changed files:
- `teleclaude/core/integration/state_machine.py` — Gap 1 path fix
- `teleclaude/core/next_machine/core.py` — Gap 2 delivery without roadmap
- `teleclaude/todo_scaffold.py` — Gap 3 best-effort worktree removal

## Resolved During Review

Two findings were auto-remediated inline:

**1. `import subprocess` inside function body (`todo_scaffold.py:272`)**
Moved to module top level at line 6. The stdlib module has no circular import
justification, unlike the local `teleclaude.core.next_machine.core` imports that
remain as function-level imports by design. Ruff and pyright both pass after the fix.

**2. No demo.md present**
The delivery changes user-visible CLI behavior (`telec todo remove` no longer raises
`RuntimeError` for worktree-bearing slugs; `telec roadmap deliver` now accepts
non-roadmap slugs with a todo directory). A no-demo marker was not present.
Created `todos/fix-bug-cleanup-pipeline-has-three-gaps-1-is/demo.md` with three
executable validation blocks verified to pass. `telec todo demo validate` confirms
3 blocks found.

## Critical

_(none remaining)_

## Important

**1. No tests for new behavioral changes**

The quality checklist claims "Tests pass: `make test`" — but `tests/unit/` does not
exist and `make test` exits 0 with the message "Test suite pending rebuild — skipping."
This is vacuously true. None of the three behavioral changes have test coverage:

- `_is_bug_slug` path correction: no test that constructs a `todos/{slug}/bug.md` and
  verifies the function returns True, nor that `todos/bugs/{slug}/bug.md` returns False.
- `deliver_to_delivered` without roadmap entry: no test for the new code path where
  `entry is None` but `todos/{slug}/` exists.
- `remove_todo` worktree removal: no test verifying best-effort worktree/branch cleanup.

Per testing policy: "New functionality must have corresponding tests." This applies to
bug fix behavioral changes. Missing tests should be added when the test suite is rebuilt.

## Suggestions

**1. `git branch -D slug` runs unconditionally**

`remove_todo` now runs `git branch -D {slug}` for every invocation, not just when a
worktree was found. For regular todos without an associated branch, this silently fails
(non-fatal, by design). For todos with an unmerged local branch but no worktree,
`-D` would force-delete it without warning. A brief comment at the call site would
clarify this is intentional best-effort behavior rather than a potential destructive
side-effect.

## Correctness Assessment

All three fixes are minimal, targeted, and correct:

- **Gap 1**: Path `todos/bugs/{slug}` → `todos/{slug}` is a one-line fix that
  eliminates the always-False return. No other behavior changes.
- **Gap 2**: The `save_roadmap` move into `else` is correct — it was previously
  unreachable when `entry is None`, and should only run when an entry was actually
  removed from the roadmap. The new fallthrough path for todo-dir-only slugs is sound.
- **Gap 3**: `RuntimeError` removal with best-effort cleanup is correct. The
  `found_worktree` flag is properly included in the "anything found" check, preventing
  false FileNotFoundError on worktree-only slugs.

No security issues. No silent failures introduced beyond the intentional best-effort
subprocess calls (which capture output and do not raise on failure by design).

## Verdict

APPROVE

Fixes address all three reported symptoms. Root cause analysis is sound. Two findings
were remediated inline (import placement, missing demo). One Important finding
(missing tests) is deferred to the test suite rebuild — the test infrastructure does
not currently exist to write them against.
