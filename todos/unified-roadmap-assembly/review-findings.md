# Review Findings: unified-roadmap-assembly

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-21

## Critical

_None._

## Important

### 1. Unused imports in test_roadmap.py

**File:** `tests/unit/core/test_roadmap.py:4,6`

`os` (line 4) and `MagicMock` (line 6) are imported but never used. This is a lint violation per Linting Requirements policy.

**Fix:** Remove `import os` and change `from unittest.mock import MagicMock, patch` to `from unittest.mock import patch`.

### 2. Build Gates unchecked in quality-checklist.md

**File:** `todos/unified-roadmap-assembly/quality-checklist.md`

All items in the Build Gates section are `[ ]` despite `state.json` showing `build: complete`. The builder should check off completed gates before review.

**Fix:** Check off the Build Gates that were satisfied during the build phase.

## Suggestions

### 3. Mixed Optional syntax in roadmap.py

**File:** `teleclaude/core/roadmap.py:10,88,152-154`

The new module uses both `from typing import Optional` (line 10, used in `read_todo_metadata` return type at line 88) and `str | None` union syntax (lines 152-154 in `append_todo`). Within a new module, one style should be chosen for consistency.

### 4. Test coverage gaps

**File:** `tests/unit/core/test_roadmap.py`

The following code paths lack test coverage:

- Empty project (no `todos/` directory) — `roadmap.py:44-45`
- Duplicate slug handling — `roadmap.py:209-211`
- Malformed `state.json` graceful handling — `roadmap.py:132-133`
- Legacy `icebox.md` parsing fallback — `roadmap.py:57-82`

These paths are inherited from the original `list_todos` implementation and are not regressions, but adding tests for the new module would improve confidence.

### 5. Container reordering index pattern

**File:** `teleclaude/core/roadmap.py:248-280`

The container reordering loop iterates over a snapshot (`list(todos)`) while rebuilding `slug_to_idx` after each move. This pattern works correctly for the practical case (hierarchical containers without circular dependencies) because `slug_to_idx` is rebuilt from the live list after every mutation. However, it is a fragile pattern that could break if future changes introduce overlapping or circular container relationships. A brief comment explaining why this is safe would help future maintainers.

## Verdict

**REQUEST CHANGES**

Required fixes (both trivial):

1. Remove unused imports in `test_roadmap.py` (lint violation)
2. Check off Build Gates in `quality-checklist.md`

The code changes themselves are correct, well-structured, and faithfully preserve all behavior from the original `list_todos` implementation. The new CLI flags (`--include-icebox`, `--icebox-only`, `--json`) work correctly. The `assemble_roadmap` function cleanly centralizes roadmap assembly logic. The `list_todos` wrapper is appropriately thin. All requirements are traced to implemented behavior.
