# Bug: Checkpoint false-positive: read-only shell commands (grep, cat, git diff) extract file paths into touched_files set, which then intersects with pre-existing dirty files from git diff --name-only HEAD, causing the checkpoint to misattribute old dirty files (e.g. state_machine.py) as modified in the current turn. Root cause: _extract_turn_file_signals in teleclaude/hooks/checkpoint/_git.py adds shell-touched paths unconditionally — it should only extract paths from commands where _command_likely_mutates_files() returns True. Fix: gate the shell path extraction on mutation intent, so grep/read commands never contribute to touched_files.

## Symptom

Checkpoint false-positive: read-only shell commands (grep, cat, git diff) extract file paths into touched_files set, which then intersects with pre-existing dirty files from git diff --name-only HEAD, causing the checkpoint to misattribute old dirty files (e.g. state_machine.py) as modified in the current turn. Root cause: _extract_turn_file_signals in teleclaude/hooks/checkpoint/_git.py adds shell-touched paths unconditionally — it should only extract paths from commands where _command_likely_mutates_files() returns True. Fix: gate the shell path extraction on mutation intent, so grep/read commands never contribute to touched_files.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
