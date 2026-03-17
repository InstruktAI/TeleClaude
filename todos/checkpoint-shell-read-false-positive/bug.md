# Bug: Checkpoint false-positive: read-only shell commands (grep, cat, git diff) extract file paths into touched_files set, which then intersects with pre-existing dirty files from git diff --name-only HEAD, causing the checkpoint to misattribute old dirty files (e.g. state_machine.py) as modified in the current turn. Root cause: \_extract_turn_file_signals in teleclaude/hooks/checkpoint/\_git.py adds shell-touched paths unconditionally — it should only extract paths from commands where \_command_likely_mutates_files() returns True. Fix: gate the shell path extraction on mutation intent, so grep/read commands never contribute to touched_files.

## Symptom

Checkpoint false-positive: read-only shell commands (grep, cat, git diff) extract file paths into touched_files set, which then intersects with pre-existing dirty files from git diff --name-only HEAD, causing the checkpoint to misattribute old dirty files (e.g. state_machine.py) as modified in the current turn. Root cause: \_extract_turn_file_signals in teleclaude/hooks/checkpoint/\_git.py adds shell-touched paths unconditionally — it should only extract paths from commands where \_command_likely_mutates_files() returns True. Fix: gate the shell path extraction on mutation intent, so grep/read commands never contribute to touched_files.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

- Read the checkpoint git scoping logic in `teleclaude/hooks/checkpoint/_git.py` and the existing characterization coverage in `tests/unit/hooks/checkpoint/test__git.py`.
- Reproduced the bug with a new regression test that simulates a turn containing a read-only shell command:
  `grep -n checkpoint teleclaude/core/integration/state_machine.py`.
- Confirmed RED by running:
  `. .venv/bin/activate && pytest tests/unit/hooks/checkpoint/test__git.py -k read_only_shell_commands -v -n 0`
- Observed failure: `_extract_turn_file_signals()` returned `{"teleclaude/core/integration/state_machine.py"}` even though the shell command was read-only, which let `_scope_git_files_to_current_turn()` treat a pre-existing dirty file as a current-turn modification.

## Root Cause

- In `teleclaude/hooks/checkpoint/_git.py`, `_extract_turn_file_signals()` extracted shell path tokens for every shell command before checking whether `_command_likely_mutates_files()` classified the command as file-mutating.
- That meant read-only commands such as `grep`, `cat`, or `git diff` could populate `touched_files` with project-relative paths.
- `_scope_git_files_to_current_turn()` then intersected those read-only path references with `git diff --name-only HEAD`, producing false-positive attribution for files that were already dirty before the current turn.

## Fix Applied

- Changed shell command handling in `teleclaude/hooks/checkpoint/_git.py` so `_extract_shell_touched_paths()` runs only when `_command_likely_mutates_files()` returns `True`.
- Added a regression test in `tests/unit/hooks/checkpoint/test__git.py` asserting that a read-only `grep` command referencing a dirty file does not contribute touched files and does not scope any git diff entries to the current turn.
- Verified GREEN with:
  `. .venv/bin/activate && pytest tests/unit/hooks/checkpoint/test__git.py -v -n 0`
