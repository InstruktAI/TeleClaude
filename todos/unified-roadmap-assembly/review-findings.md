# Review Findings: unified-roadmap-assembly

**Review round:** 2
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-21

## Critical

_None._

## Important

_None._

## Suggestions

### 1. Test coverage gaps (carried from round 1)

**File:** `tests/unit/core/test_roadmap.py`

The following code paths lack dedicated test coverage:

- Empty project (no `todos/` directory) — `roadmap.py:43-44`
- Duplicate slug handling — `roadmap.py:208-210`
- Malformed `state.json` graceful handling — `roadmap.py:131-132`
- Legacy `icebox.md` parsing fallback — `roadmap.py:56-81`

These paths are inherited from the original `list_todos` implementation and are not regressions. Not blocking.

## Round 1 Fix Verification

| Finding                              | Status                                           |
| ------------------------------------ | ------------------------------------------------ |
| #1 Unused imports in test_roadmap.py | Fixed — `os` and `MagicMock` removed             |
| #2 Build gates unchecked             | Fixed — all gates now `[x]`                      |
| #3 Mixed Optional syntax             | Addressed — consistent `str \| None` throughout  |
| #5 Container reordering comment      | Addressed — explanatory comment at lines 245-249 |

## Verdict

**APPROVE**

The extraction is clean and complete. `assemble_roadmap` faithfully preserves all behavior from the original `list_todos` implementation. The new CLI flags (`--include-icebox`, `--icebox-only`, `--json`) are correctly wired. The `list_todos` wrapper is appropriately thin. All 6 success criteria are met. Lint, type checking, and roadmap-specific tests all pass.
