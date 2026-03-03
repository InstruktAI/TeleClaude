# DOR Report: slug-helper

## Summary

Extract scattered slug handling into a shared `teleclaude/slug.py` module. Straightforward
refactoring with clear scope — every code location is identified and the approach follows
existing patterns in the codebase.

## Gate Assessment (Final)

**Verdict: pass — score 9/10**

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
**Pass.** Standard extract-module refactoring. All code locations identified. The
`ensure_unique_slug` pattern already exists in `content_scaffold.py` — it's being
generalized, not invented. Caller slug desync risk is now explicitly addressed in the
plan (task 2.3) with a concrete fix: derive actual slug from `todo_dir.name`.

### 5. Research Complete
**Pass (auto-satisfied).** No third-party dependencies. Pure internal refactoring.

### 6. Dependencies & Preconditions
**Pass.** No external dependencies. No config changes. No environment requirements.

### 7. Integration Safety
**Pass.** The behavior change (todo/bug skeleton collision → counter-suffix instead of
`FileExistsError`) is an improvement. All callers that catch `FileExistsError` are
identified in requirements. The slug desync risk (callers using original `slug` after
a potentially suffixed return) is documented in requirements and the plan prescribes
the fix: `slug = todo_dir.name` at each affected site (`telec.py:2829`, `telec.py:2253`,
`preparation.py:790`).

### 8. Tooling Impact
**Pass (auto-satisfied).** No tooling or scaffolding changes.

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

None. All prior blockers resolved:

1. ~~Caller slug desync~~ — plan task 2.3 now includes explicit sub-task for deriving
   slug from `todo_dir.name`. Requirements document the risk.
2. ~~Misleading checkmarks~~ — all phases 1–3 cleared to `[ ]`.
3. ~~File scope gap~~ — `preparation.py` now listed in task 2.3 `File(s):` header.
