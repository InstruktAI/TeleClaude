# Requirements: fix-demo-runner

## Goal

Redesign the demo system from a rigid shell-command ceremony into an AI-operated,
testable demonstration framework. The AI is the presenter and operator — it runs
commands, presses TUI keys, drives Playwright, narrates to the user. The user watches.

## Context

The current demo system has a `demo` field in `snapshot.json` — a single shell command.
The `/next-demo` command runs it and renders a celebration widget. This is too rigid:
TUI features can't be demoed with a shell command, web UI changes need Playwright,
messaging features need adapter interaction. The presenter should adapt to the delivery.

## Core concept: demo.md

A freeform markdown file with steps for the AI presenter to execute. Written by the
architect (draft) and builder (refined). Contains:

- **Executable code blocks** (```bash) — extracted and run by `telec todo demo` for
  automated validation. Testable upfront.
- **Guided steps** — instructions for the AI to operate the system (TUI keypresses,
  Playwright actions, API calls) and narrate to the user.
- **Verification steps** — assertions the AI checks ("output should contain X",
  "user should see Y").

The AI reads `demo.md` verbatim and executes it. No schema, no ceremony. One AI
writes instructions for another AI to follow.

## Scope

### In scope

- **demo.md artifact**: introduce as a todo lifecycle artifact (drafted in prepare,
  refined in build, copied to `demos/{slug}/` at delivery)
- **CLI runner rewrite**: `telec todo demo <slug>` reads `demo.md`, extracts fenced
  bash code blocks, executes them sequentially, reports pass/fail
- **/next-demo command rewrite**: conversational presenter that reads `demo.md` and
  executes ALL steps (code blocks + guided + verification) as the narrator/operator
- **Demo procedure doc update**: replace shell-command ceremony with demo.md framework,
  describe the prepare→build→present lifecycle
- **Demo artifact spec update**: drop `demo` field from snapshot.json, add `demo.md`
  as the demonstration artifact
- **Lifecycle overview update**: correct the demo phase description
- **Existing demos**: write `demo.md` for `themed-primary-color` and `tui-markdown-editor`
- **Todo scaffold**: add `demo.md` template to the scaffold
- **Prepare-draft procedure**: add demo.md drafting guidance (architect defines how
  to prove the delivery works)

### Out of scope

- MCP wrapper changes (MCP is being eliminated)
- Playwright integration (the framework supports it but specific Playwright tooling
  is not part of this todo — agents already have Playwright available)
- Changes to snapshot.json structure beyond dropping the `demo` field

## Success Criteria

- [ ] `telec todo demo themed-primary-color` extracts code blocks from `demo.md`,
      runs them, exits 0
- [ ] `telec todo demo tui-markdown-editor` same
- [ ] `/next-demo themed-primary-color` reads `demo.md` and walks through all steps
      conversationally
- [ ] New todos scaffolded with `telec todo create` include a `demo.md` template
- [ ] Demo procedure doc describes the demo.md framework
- [ ] Demo artifact spec reflects demo.md instead of demo field
- [ ] Lifecycle overview describes demo phase accurately

## Constraints

- No MCP infrastructure investment
- demo.md is freeform markdown — no rigid schema beyond "fenced bash blocks are
  executable"
- Backward compatibility: demos without demo.md fall back to snapshot.json `demo`
  field (existing CLI behavior) during transition
- The AI is the operator. Minimize "ask the user to do X" — prefer the AI doing it
  and narrating what happened

## Risks

- TUI operation by the AI (sending keypresses) depends on the agent having tmux
  access to the TUI pane. This already works via PaneManagerBridge. Low risk.
- Code block extraction is a simple regex over fenced blocks. Edge cases with
  nested blocks are unlikely but possible. Keep the parser simple.
