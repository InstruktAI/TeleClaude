# Bug: Prepare state machine stuck in input_assessment: check_file_has_content uses repo root cwd instead of worktree path

## Symptom

Prepare state machine stuck in input_assessment: check_file_has_content uses repo root cwd instead of worktree path

## Detail

## Bug

`_prepare_step_input_assessment` (prepare_steps.py:75) calls `check_file_has_content(cwd, f'todos/{slug}/requirements.md')` where `cwd` is the canonicalized repo root. But the discovery worker writes requirements.md to the worktree (`trees/{slug}/todos/{slug}/requirements.md`).

State I/O functions (`read_phase_state`, `write_phase_state`) correctly resolve to the worktree via `_resolve_state_cwd()`, but the file content check does not. The repo root still has the scaffold template, so `_is_scaffold_template()` returns True, `check_file_has_content()` returns False, and the machine dispatches another discovery worker — infinite loop.

## Reproduction

1. `telec todo prepare config-independent-schemas` — dispatches discovery
2. Discovery worker writes requirements.md in worktree, commits
3. `telec todo mark-phase config-independent-schemas --phase requirements --status complete` — stamps artifact digest
4. `telec todo prepare config-independent-schemas` — dispatches discovery AGAIN (should advance to requirements_review)

## Root cause

prepare_steps.py:75: `check_file_has_content(cwd, ...)` — `cwd` is repo root, should resolve to worktree like state I/O does.

Same pattern likely affects other `check_file_has_content` calls in prepare_steps.py (plan drafting, test specs, etc).

## Fix

Apply `_resolve_state_cwd(cwd, slug)` (or equivalent worktree resolution) to file content checks in prepare_steps.py, not just state I/O. Alternatively, check the artifact stamp in state.yaml instead of re-reading file content.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-26

## Investigation

Traced the call chain in `_prepare_step_input_assessment` (prepare_steps.py:75):
`check_file_has_content(cwd, f"todos/{slug}/requirements.md")` — `cwd` is the
canonicalized repo root passed down from `telec todo prepare`. The discovery
worker commits its output to `trees/{slug}/todos/{slug}/requirements.md`, not
`todos/{slug}/requirements.md` on the repo root. Because `check_file_has_content`
uses the raw `cwd`, it reads the scaffold template at the repo root, which
`_is_scaffold_template()` returns True for, so `check_file_has_content` returns
False — and the machine re-dispatches discovery indefinitely.

`write_phase_state` / `read_phase_state` both call `_resolve_state_cwd(cwd, slug)`
first, which checks whether `trees/{slug}/` exists and, if so, returns that path.
The file-content checks did not apply the same resolution.

## Root Cause

`check_file_has_content(cwd, ...)` in `_prepare_step_input_assessment`,
`_prepare_step_triangulation`, and `_prepare_step_plan_drafting` used the
unresolved repo-root `cwd` instead of the worktree-resolved path. State I/O
(`write_phase_state`, `read_phase_state`) already called `_resolve_state_cwd`
to prefer the worktree; the file-content checks did not.

## Fix Applied

- `prepare_steps.py`: imported `_resolve_state_cwd` from `state_io` and wrapped
  the three `check_file_has_content` call sites with it:
  - `_prepare_step_input_assessment` (line 75)
  - `_prepare_step_triangulation` (line 110)
  - `_prepare_step_plan_drafting` (line 383)
- `test_prepare_steps.py`: added three regression tests that write the artifact
  only in the worktree (`trees/{slug}/todos/{slug}/...`) and verify each step
  advances correctly. Added docstrings to pre-existing test functions that lacked
  them (surfaced by session-scoped pylint).
