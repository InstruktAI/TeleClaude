# Bug: check_file_has_content does not resolve to worktree — prepare machine loops on split children

## Symptom

check_file_has_content does not resolve to worktree — prepare machine loops on split children

## Detail

check_file_has_content in path_checks.py uses raw cwd without worktree resolution. read_phase_state and write_phase_state use _resolve_state_cwd to prefer trees/{slug}/, but check_file_has_content does not. This causes the prepare machine to loop on split children because it checks for artifacts at project-root/todos/{slug}/ instead of trees/{slug}/todos/{slug}/. The fix is to apply the same _resolve_state_cwd pattern (or equivalent) inside check_file_has_content. Affected file: teleclaude/core/next_machine/path_checks.py:16

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-23

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
