# DOR Report: state-machine-gate-sharpening

## Gate Verdict: PASS (score 9/10)

All eight DOR gates satisfied. Line references verified against source code.
Plan-to-requirement fidelity confirmed — every plan task traces to a success criterion,
no contradictions found.

### Gate 1: Intent & Success
**Status:** Satisfied

Problem statement in `input.md` names three specific false-invalidation patterns with exact
line references, all confirmed in source. Seven success criteria (SC-1 through SC-7) are
concrete and independently testable.

### Gate 2: Scope & Size
**Status:** Satisfied

All changes confined to `teleclaude/core/next_machine/core.py`. Three independent fixes,
each 10-30 lines of change. Two small helper functions added. Fits a single AI session.

### Gate 3: Verification
**Status:** Satisfied

Ten specific test cases defined in implementation plan Phase 2:
- `_has_meaningful_diff`: mock subprocess for file list filtering, merge commit exclusion, error fail-safe.
- Stale baseline guard integration: infrastructure-only diff vs real diff.
- Gate failure with `review_round > 0` vs `== 0`.
- `_count_test_failures` parser: various pytest output strings.
- `run_build_gates` retry path: mocked 1-2 failures triggers retry; >2 does not.
Edge cases explicitly handled: subprocess errors (fail-safe), unparseable pytest output (no retry),
retry failure (combined output).

### Gate 4: Approach Known
**Status:** Satisfied

All three fixes follow established codebase patterns:
- Helper functions with subprocess calls (precedent: `_get_head_commit` at line ~375).
- Conditional phase marking (precedent: repair blocks at lines 2990-3002).
- `read_phase_state` returns full state dict including `review_round` — verified at line 778.
- Line references verified: 3010 (SHA comparison), 3090-3097 (gate failure reset),
  3105-3111 (artifact verification reset), 416-471 (`run_build_gates`).

### Gate 5: Research Complete
**Status:** Automatically satisfied

No third-party tools or integrations introduced. Uses existing `git`, `pytest`, `subprocess`.

### Gate 6: Dependencies & Preconditions
**Status:** Satisfied

No prerequisite tasks. No config changes. No external system dependencies. Active in roadmap.

### Gate 7: Integration Safety
**Status:** Satisfied

All three fixes narrow existing reset conditions — they never widen them:
- Fix 1: same guard, smarter check (diff-based filtering vs SHA equality).
- Fix 2: conditional preservation (only when `review_round > 0`).
- Fix 3: retry on small failure counts only (1-2 failures).
Fail-safe defaults preserve existing behavior on any error path.
Plan correctly extends Fix 2 to both the gate failure block (3090-3097)
and the artifact verification block (3105-3111).

### Gate 8: Tooling Impact
**Status:** Automatically satisfied

No tooling or scaffolding changes.

## Plan-to-Requirement Fidelity

| Requirement | Plan Task | Verified |
|---|---|---|
| SC-1: merge/infra diff → approval holds | Task 1.1: `_has_meaningful_diff` filters `todos/`, `.teleclaude/`, merge commits | Yes |
| SC-2: real diff → invalidation | Task 1.1: returns `True` when non-infra files remain | Yes |
| SC-3: gate fail + review_round > 0 → build stays complete | Task 1.2: conditional on `review_round > 0` | Yes |
| SC-4: gate fail + review_round == 0 → reset to started | Task 1.2: else branch preserves existing behavior | Yes |
| SC-5: <=2 failures → retry with `pytest --lf` | Task 1.3: `_count_test_failures` + retry block | Yes |
| SC-6: >2 failures → no retry | Task 1.3: count check skips retry | Yes |
| SC-7: retry fails → combined output | Task 1.3: appends both run outputs | Yes |

No contradictions between plan and requirements.

## Open Questions

None.

## Assumptions

- Pytest output format includes `"N failed"` in the summary line (standard pytest behavior).
  Parser uses lenient regex, falls back to no-retry if format differs.
- The `.venv/bin/pytest` path exists in worktrees (same assumption as `tools/test.sh`).
  Fallback to bare `pytest` if not found.
- Merge commits from main are the primary source of false SHA mismatches after review approval.
