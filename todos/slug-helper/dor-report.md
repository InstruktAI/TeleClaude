# DOR Report: slug-helper

## Summary

Extract scattered slug handling into a shared `teleclaude/slug.py` module. Straightforward
refactoring with clear scope — every code location is identified and the approach follows
existing patterns in the codebase.

## Gate Assessment (Final)

**Verdict: needs_work — score 7/10**

### 1. Intent & Success
**Pass.** Problem statement is explicit: slug logic is duplicated across 5+ locations with
inconsistent behavior. Success criteria are concrete and testable (import checks, grep
verification, test pass).

### 2. Scope & Size
**Pass.** Atomic refactoring — one new module, four caller updates, test migration. Fits
a single session. No cross-cutting architectural changes.

### 3. Verification
**Pass.** Existing test suite covers callers. New unit tests for the module itself.
`make test` + `make lint` as final gate. Demo includes grep-based duplication checks.

### 4. Approach Known
**Pass with finding.** The extract-module pattern is standard. However, the plan does not
fully account for the cascading effect of the `FileExistsError` → `ensure_unique_slug`
behavior change on callers that continue to use the original `slug` variable after calling
`create_todo_skeleton` / `create_bug_skeleton`. See blocker #1.

### 5. Research Complete
**Pass (auto-satisfied).** No third-party dependencies. Pure internal refactoring.

### 6. Dependencies & Preconditions
**Pass.** No external dependencies. No config changes. No environment requirements.

### 7. Integration Safety
**Needs work.** The behavior change from `FileExistsError` to counter-suffix uniqueness is
well-intentioned, but the plan incompletely addresses its cascading effects. Three callers
use the original `slug` variable after the skeleton function call:

1. **`telec.py:2829`** — creates a git branch with `slug`. If `ensure_unique_slug` changed
   the slug to `fix-something-2`, the branch is still named `fix-something` while the
   directory is `fix-something-2`. **This is a real bug.**
2. **`telec.py:2253`** — prints `"Updated dependencies for {slug}"`. Misleading if suffixed.
3. **`preparation.py:790`** — constructs `filepath = f"{project_root}/todos/{slug}/{filename}"`.
   Points to wrong directory if suffixed.

**Fix:** Both skeleton functions already return `Path` (the `todo_dir`). After the call,
callers must derive the actual slug: `slug = todo_dir.name`. The plan needs explicit
sub-tasks for each affected caller site.

### 8. Tooling Impact
**Pass (auto-satisfied).** No tooling or scaffolding changes.

## Additional Findings

### Misleading checkmarks
All tasks in phases 1–3 of the implementation plan have `[x]` checkmarks, but no
implementation exists (`teleclaude/slug.py` and `tests/unit/test_slug.py` are both absent).
This would confuse a builder into thinking the work is done. All checkmarks must be
cleared to `[ ]`.

### Missing file scope
Task 2.3 mentions `preparation.py` in its description text ("and TUI `preparation.py`")
but lists only `teleclaude/cli/telec.py` in its `File(s):` header. Either add
`preparation.py` to task 2.3's file scope or create a separate task for it.

## Assumptions

- The `blocked_followup._normalize_slug` and `roadmap.slugify_heading` are correctly
  scoped as out-of-scope (verified — they serve different domains with different charset rules).
- `resource_validation.py:294` and `session_auth.py:94` normalization patterns are also
  correctly out-of-scope (verified — different charsets, different domains).
- The behavior change from `FileExistsError` to counter-suffix is desired
  (confirmed by input.md: "Todos get counter-suffix uniqueness like content already has").

## Open Questions

None.

## Blockers

1. **Caller slug desync** — plan must add explicit sub-tasks for updating callers to use
   `todo_dir.name` after `create_todo_skeleton` / `create_bug_skeleton` calls. Affected:
   `telec.py:2829`, `telec.py:2253`, `preparation.py:790`.
2. **Misleading checkmarks** — all `[x]` in phases 1–3 must be `[ ]`.
3. **File scope gap** — `preparation.py` must be listed in task 2.3 or get its own task.

## Remediation

All three blockers are plan-level fixes, not research or design questions. A single pass
through the implementation plan resolves them. No human decision required.
