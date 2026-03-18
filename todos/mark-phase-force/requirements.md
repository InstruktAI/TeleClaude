# Requirements: mark-phase-force

## Goal

Fix the three wrong environment guards on `mark-phase`, make worktree resolution
flexible, and add `--force` to bypass the remaining guard unconditionally.

`mark-phase` is a state setter. The prepare lifecycle and work state machine own
sequencing and correctness — `mark-phase` must not second-guess them with artifact
content checks.

---

## Problem Analysis

`POST /todos/mark-phase` enforces three guards for build/review phases that are wrong
or misplaced:

**1. Worktree must exist at `trees/{slug}/` (wrong abstraction)**
Blocks any state write for todos that have no worktree yet — e.g. a todo prepared
inline on main. The real question is: where is `state.yaml`? If the worktree exists,
use it. If not, fall back to `cwd`. The 404 gate belongs only when `--force` is absent
and the worktree is missing — that is still a reasonable safety rail.

**2. No stash entries for terminal statuses (wrong signal)**
Stash is repo-level state. It has no logical connection to whether a phase transition
is valid. This check is always wrong here and must be removed.

**3. No uncommitted changes for all terminal statuses (too broad)**
Correct for `build:complete` — you must commit your work before declaring the build
done. Wrong for `review:approved`, `review:changes_requested`, `review:complete` —
reviewer notes may legitimately be uncommitted when the verdict is written.

---

## Requirements

### R1 — Flexible cwd resolution for build/review phases

For build/review phases, effective state directory:
1. If `trees/{slug}/` exists → use it.
2. If it does not exist AND `--force` is set → use `cwd` (main repo root).
3. If it does not exist AND `--force` is not set → 404 (unchanged behavior).

### R2 — Remove the stash guard entirely

The stash check is removed from `mark-phase`. No phase transition depends on stash
state. This is not wrapped in `--force` — it is unconditionally gone.

### R3 — Narrow the uncommitted-changes guard to `build:complete` only

Retain: `build:complete`, `build:approved`.
Remove: `review:approved`, `review:complete`, `review:changes_requested`.
With `--force`: skip even the narrowed build guard.

### R4 — Add `--force` flag to bypass remaining guards

When `force=True`:
- Skip the worktree 404 gate (fall back to `cwd` instead — R1).
- Skip the uncommitted-changes check for `build:complete` (R3).
- All other behavior unchanged.

### R5 — CLI exposes `--force`

`handle_todo_mark_phase` parses `--force` and sends `"force": True` in the request body.
Docstring and examples updated.

### R6 — No new artifact or content guards

`mark-phase` does not validate artifact content (requirements.md, implementation-plan.md,
etc.). That responsibility belongs to the prepare lifecycle and work state machine. Adding
content guards here would break workflows that legitimately pass through empty artifact states.

---

## Success Criteria

- `telec todo mark-phase <slug> --phase build --status pending --force` succeeds when no
  worktree exists (uses `cwd` fallback).
- `telec todo mark-phase <slug> --phase build --status complete` still fails with 409 when
  uncommitted changes exist (unchanged for this case).
- `telec todo mark-phase <slug> --phase review --status approved` succeeds even with
  uncommitted changes (no longer blocked).
- `telec todo mark-phase <slug> --phase build --status complete --force` succeeds even
  with uncommitted changes.
- Calling `mark-phase` when stash entries exist no longer raises 409 for any phase.
- Pre-commit hooks pass.

## Constraints

- State written is identical whether or not `--force` is used.
- Prepare/verdict phases (`requirements_review`, `test_spec_review`, `plan_review`,
  `prepare`) are unchanged — they already operate on `cwd` with no environment guards.
- `mark-ready` is not changed.

## Out of Scope

- Adding content validation to any phase.
- Changing `mark-ready` or deprecating it.
- Changing which fields `mark-phase` can set.
- Changing `review_round` increment behavior.
