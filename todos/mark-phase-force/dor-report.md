# DOR Gate Report: mark-phase-force

**Verdict:** PASS
**Score:** 9/10
**Assessed:** 2026-03-17

---

## Gate Results

| Gate | Result | Notes |
|------|--------|-------|
| 1. Intent & success | PASS | Problem: three wrong guards. Outcome: remove/fix guards + `--force`. No new artifact checks. |
| 2. Scope & size | PASS | One route file, one CLI file. ~25 lines changed. One builder session. |
| 3. Verification | PASS | 6 xfail test specs across route and CLI. |
| 4. Approach known | PASS | All changes are in-place replacements. No new abstractions. |
| 5. Research complete | PASS | No third-party dependencies. |
| 6. Dependencies | PASS | No blockers. `PhaseName` already importable from `_types`. |
| 7. Integration safety | PASS | Stash removal is unconditional but only affects mark-phase — never load-bearing. |
| 8. Tooling impact | PASS | No scaffolding changes. |

## Key Design Decisions

- **No artifact content guards added** — `mark-phase` is a state setter. Lifecycle
  correctness is the state machine's responsibility, not the setter's.
- **Stash guard removed unconditionally** — not wrapped with `--force`. It was never
  correct. Wrapping it would preserve a wrong behavior for the non-force path.
- **Uncommitted guard narrowed, not removed** — `build:complete` correctly requires a
  clean tree. Review phases do not.
- **Worktree fallback, not elimination** — missing worktree without `--force` still
  returns 404. The 404 is the safety rail; `--force` is the acknowledged bypass.

## Score Justification

-1: xfail test files not yet written; builder writes them first.
