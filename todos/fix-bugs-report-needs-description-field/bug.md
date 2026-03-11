# Bug: telec bugs report only accepts a single positional description string with no way to provide a detailed body. Bug.md files are created with just the symptom line and empty sections. The command should accept a --description flag for a detailed body, or open an editor, so fix workers have sufficient context to investigate.

## Symptom

telec bugs report only accepts a single positional description string with no way to provide a detailed body. Bug.md files are created with just the symptom line and empty sections. The command should accept a --description flag for a detailed body, or open an editor, so fix workers have sufficient context to investigate.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-11

## Investigation

CLI handler `_handle_bugs_report` in `teleclaude/cli/telec.py:3345` only parses `--slug`. Template `templates/todos/bug.md` had no `{body}` placeholder. `create_bug_skeleton` in `teleclaude/todo_scaffold.py:110` had no `body` parameter.

## Root Cause

Missing `--body` flag in CLI, missing `body` param in `create_bug_skeleton`, missing `{body}` section in template.

## Fix Applied

- Added `--body` flag to `_handle_bugs_report` and CLI `CommandDef`
- Added `body` keyword param to `create_bug_skeleton`
- Added `## Detail` section with `{body}` placeholder to `templates/todos/bug.md`
