# DOR Report: fix-demo-runner

## Assessment

**Score:** 8/10 (draft — pending formal gate)
**Assessed:** 2026-02-22

## Summary

Redesign the demo system from a single shell-command field to `demo.md` — freeform
markdown with executable code blocks and guided steps. The AI is both presenter and
operator. Code blocks provide upfront testability via CLI; guided steps provide the
full demo experience.

Touches: CLI runner (Python), command artifact, 4 doc files, 2 existing demos,
todo scaffold. No MCP investment.

## Gate Analysis

| #   | Gate               | Draft | Detail                                                                                  |
| --- | ------------------ | ----- | --------------------------------------------------------------------------------------- |
| 1   | Intent & success   | PASS  | Clear problem + solution. 7 success criteria, all testable.                             |
| 2   | Scope & size       | PASS  | ~5 phases, mostly doc/artifact edits + one CLI function rewrite. Single session.        |
| 3   | Verification       | PASS  | CLI exit codes for demo validation, artifact review for docs/command.                   |
| 4   | Approach known     | PASS  | Code block extraction is simple regex. Command artifact is markdown. Docs are markdown. |
| 5   | Research           | N/A   | No third-party dependencies.                                                            |
| 6   | Dependencies       | PASS  | `demo-runner` delivered. No blockers.                                                   |
| 7   | Integration safety | PASS  | Backward compatible: falls back to snapshot.json demo field when demo.md absent.        |
| 8   | Tooling impact     | PASS  | Todo scaffold updated. `telec sync` after to deploy.                                    |

## Confirmed Against Codebase

- `teleclaude/cli/telec.py:1216-1225` — current CLI reads `demo` field from snapshot.json,
  needs rewrite to prefer `demo.md` with code block extraction
- `demos/themed-primary-color/snapshot.json` — missing `demo` field, needs `demo.md` instead
- `demos/tui-markdown-editor/snapshot.json` — same
- `agents/commands/next-demo.md` — hardcodes widget ceremony, needs full rewrite
- `docs/global/software-development/procedure/lifecycle/demo.md` — prescribes shell command
  - widget, needs demo.md framework
- `docs/project/spec/demo-artifact.md` — spec has `demo` field, needs demo.md addition
- `docs/global/software-development/procedure/lifecycle-overview.md:61` — references
  `demo.sh`, needs correction
- `teleclaude/todo_scaffold.py` — scaffolds 5 files, needs demo.md added
- `templates/todos/` — needs demo.md template

## Open Questions

None. Design direction confirmed in conversation with Mo.
