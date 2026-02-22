# DOR Report: fix-demo-runner

## Assessment

**Score:** 8/10 (draft — pending formal gate)
**Assessed:** 2026-02-22

## Summary

Redesign the demo system: `demo.md` replaces the `demo` shell command field.
Freeform markdown with executable bash code blocks (testable) and guided steps
(AI-operated presentation). `telec todo demo <slug>` becomes a demo validator
(build gate). `/next-demo` becomes a conversational presenter. The demo is the
ultimate functional test — if it doesn't pass, the build isn't done.

Key principles: testability is the default (AI can spin up its own TUI, run
Playwright, start sessions — almost nothing is "not automatable"). Demos are
non-destructive (create own test data, clean up). `<!-- skip-validation: reason -->`
for the rare block that can't be automated. Bug fixes get demos too.

Touches: CLI runner (Python), build procedure, command artifact, 4 doc files,
2 existing demos, todo scaffold. No MCP investment.

## Gate Analysis

| #   | Gate               | Draft | Detail                                                                                  |
| --- | ------------------ | ----- | --------------------------------------------------------------------------------------- |
| 1   | Intent & success   | PASS  | Clear problem + solution. 8 success criteria, all testable.                             |
| 2   | Scope & size       | PASS  | 6 phases, mostly doc/artifact edits + one CLI function rewrite. Single session.         |
| 3   | Verification       | PASS  | CLI exit codes for demo validation, artifact review for docs/command.                   |
| 4   | Approach known     | PASS  | Code block extraction is simple regex. Command artifact is markdown. Docs are markdown. |
| 5   | Research           | N/A   | No third-party dependencies.                                                            |
| 6   | Dependencies       | PASS  | `demo-runner` delivered. No blockers.                                                   |
| 7   | Integration safety | PASS  | Backward compatible: falls back to snapshot.json demo field when demo.md absent.        |
| 8   | Tooling impact     | PASS  | Todo scaffold updated (adds demo.md). `telec sync` after to deploy.                     |

## Confirmed Against Codebase

- `teleclaude/cli/telec.py:1216-1225` — current CLI reads `demo` field from snapshot.json,
  needs rewrite to prefer `demo.md` with code block extraction
- `demos/themed-primary-color/snapshot.json` — missing `demo` field, needs `demo.md` instead
- `demos/tui-markdown-editor/snapshot.json` — same
- `agents/commands/next-demo.md` — hardcodes widget ceremony, needs full rewrite
- `docs/global/software-development/procedure/lifecycle/demo.md` — prescribes shell command
  - widget, needs demo.md framework
- `docs/global/software-development/procedure/lifecycle/build.md` — no demo validation step,
  needs addition
- `docs/project/spec/demo-artifact.md` — spec has `demo` field, needs demo.md addition
- `docs/global/software-development/procedure/lifecycle-overview.md:61` — references
  `demo.sh`, needs correction
- `teleclaude/todo_scaffold.py` — scaffolds 5 files, needs demo.md added
- `templates/todos/` — needs demo.md template
- `templates/todos/quality-checklist.md` — has "Demo is runnable and verified" gate,
  needs specificity update

## Open Questions

None. Design direction confirmed in conversation with Mo.
