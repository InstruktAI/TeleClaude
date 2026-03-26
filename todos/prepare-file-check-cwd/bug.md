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

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
