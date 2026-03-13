# Review Findings: rlf-core-machines

## Review Metadata

- **Review round:** 2
- **Scope:** Delta review after R1 fix round + demo promotion
- **Review baseline:** `baffc07f4e597b43cb70d9aa1267de53e9d3eb19`
- **Merge base:** `a4cfe108db4cdb0a52e35eefb6ad517569418596`

## Critical

(none)

## Important

(none — all resolved)

## Suggestions

(none — all resolved)

## Resolved During Review (R2)

### R2-F1: Demo promotion regressed R1-F2 fix (Important → Resolved)

**Location:** `todos/rlf-core-machines/demo.md:44`, `demos/rlf-core-machines/demo.md:44`
**Issue:** The demo promotion commit (`439f4c227`) copied the unfixed `todos/` demo to `demos/`, overwriting the R1-F2 fix. The source file (`todos/demo.md`) was never updated during R1 — only the promoted `demos/` copy was fixed. Result: threshold reverted to 850 (should be 800 per requirements) and `formatters.py` dropped from validation list.
**Fix:** Applied R1-F2 fix to both `todos/` and `demos/` demo files: threshold set to 800, `formatters.py` added to sub-module list.

## Resolved During Review (R1)

### R1-F1: `step_functions.py` exceeds 800-line hard ceiling (Important → Resolved)

**Location:** `teleclaude/core/integration/step_functions.py` (was 833 lines, now 726)
**Fix:** Extracted instruction formatters into `teleclaude/core/integration/formatters.py` (117 lines). Updated imports in `state_machine.py`. All modules now under 800 lines.
**Commit:** `4bdf5a359`

### R1-F2: Demo validation threshold mismatch (Suggestion → Resolved)

**Location:** `demos/rlf-core-machines/demo.md:44`
**Fix:** Updated demo threshold from 850 to 800 to match requirements. Added `formatters.py` to the sub-module validation list.
**Commit:** `4bdf5a359`
**Note:** Regressed by demo promotion (`439f4c227`). Re-fixed in R2-F1.

### R1-F3: Redundant explicit re-exports in `__init__.py` (Suggestion → Resolved)

**Location:** `teleclaude/core/next_machine/__init__.py:7-9`
**Fix:** Removed redundant explicit re-exports of `next_create`, `next_prepare`, `next_work` (already covered by wildcard import from core.py).
**Commit:** `4bdf5a359`

## R2 Verification Summary

### Code integrity

No source code changed since R1 APPROVE. All 20 modules remain under 800 lines (largest: prepare_steps.py at 757). All R1 code fixes (formatters extraction, __init__.py cleanup) intact.

### Module line counts (verified)

| Module | Lines |
|--------|-------|
| _types.py | 243 |
| state_io.py | 572 |
| roadmap.py | 260 |
| icebox.py | 216 |
| delivery.py | 270 |
| git_ops.py | 290 |
| slug_resolution.py | 280 |
| output_formatting.py | 285 |
| build_gates.py | 441 |
| worktrees.py | 361 |
| prepare_events.py | 185 |
| prepare_steps.py | 757 |
| work.py | 721 |
| prepare.py | 132 |
| create.py | 284 |
| core.py (facade) | 208 |
| integration/state_machine.py | 278 |
| integration/checkpoint.py | 176 |
| integration/step_functions.py | 726 |
| integration/formatters.py | 117 |

### Tests

139 passed, 0 failed. No test changes since R1.

### Demo

6 executable blocks validated. Threshold corrected to 800. `formatters.py` included in validation list.

---

## Verdict

- [x] APPROVE
- [ ] REQUEST CHANGES

R2-F1 (demo regression) auto-remediated. All source code unchanged since R1 APPROVE. 139 tests pass. All modules under 800 lines. Backward-compatible imports verified.
