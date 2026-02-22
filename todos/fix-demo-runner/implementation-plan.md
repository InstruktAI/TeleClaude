# Implementation Plan: fix-demo-runner

## Overview

Redesign the demo system around `demo.md` — a freeform markdown artifact with
executable code blocks and guided steps. Touches the CLI runner, command artifact,
procedure docs, spec docs, todo scaffold, and existing demos. No MCP changes.

## Phase 1: CLI runner — extract and run code blocks from demo.md

### Task 1.1: Update `_handle_todo_demo` to prefer demo.md

**File:** `teleclaude/cli/telec.py`

- [ ] When running a demo with slug: check for `demo.md` first (in `demos/{slug}/`),
      fall back to `snapshot.json` `demo` field for backward compatibility
- [ ] If `demo.md` exists: extract all fenced ```bash code blocks
- [ ] Execute each block sequentially via `subprocess.run(block, shell=True, cwd=demo_path)`
- [ ] Report per-block pass/fail with the block content as context
- [ ] Exit 0 only if all blocks pass, exit 1 on first failure
- [ ] Keep the listing mode (`telec todo demo` with no slug) unchanged — it reads
      snapshot.json for title/version/date

### Task 1.2: Code block extraction utility

**File:** `teleclaude/cli/telec.py` (inline, no separate module)

- [ ] Simple regex: extract content between ` ```bash ` and ` ``` ` fences
- [ ] Skip blocks inside HTML comments or explicitly marked `<!-- skip-demo -->`
- [ ] Return list of (line_number, block_content) tuples for reporting

## Phase 2: Write demo.md for existing demos

### Task 2.1: themed-primary-color demo.md

**File:** `demos/themed-primary-color/demo.md`

- [ ] Verify theme module loads and contains expected theme names:
  ```bash
  python -c "from teleclaude.cli.theme import ..."
  ```
- [ ] Guided: describe the visual experience — warm orange at agent level, peaceful
      gray at level 0, how to toggle via carousel
- [ ] Verification: tell the presenter to open telec and confirm theme colors

### Task 2.2: tui-markdown-editor demo.md

**File:** `demos/tui-markdown-editor/demo.md`

- [ ] Verify editor module is importable:
  ```bash
  python -c "from teleclaude.cli.editor import ..."
  ```
- [ ] Guided: describe launching the editor via 'e' key in preparation view,
      markdown syntax highlighting, save/cancel behavior
- [ ] Verification: tell the presenter to open telec, navigate to prep view, press 'e'

## Phase 3: Command artifact and docs

### Task 3.1: Rewrite /next-demo command

**File:** `agents/commands/next-demo.md`

- [ ] Purpose: conversational presenter that reads `demo.md` and walks the user through
- [ ] No slug: list available demos (via `telec todo demo`), ask which to present
- [ ] With slug: read `demos/{slug}/demo.md`, execute steps sequentially
- [ ] For code blocks: run via Bash, show output to user, narrate results
- [ ] For guided steps: operate the system (TUI keys, CLI, API) and narrate
- [ ] For verification: check assertions, report pass/fail to user
- [ ] On failure: offer to run `telec bugs report` with the failure context
- [ ] Celebrate with snapshot narrative (five acts) after successful demo — conversationally,
      not as a fixed widget
- [ ] Drop all render_widget/celebration-widget references

### Task 3.2: Update demo procedure doc

**File:** `docs/global/software-development/procedure/lifecycle/demo.md`

- [ ] Replace "The demo field" section with demo.md framework description
- [ ] Creation: architect drafts demo.md in prepare phase (how to prove it works),
      builder refines with real implementation knowledge in build phase
- [ ] Presentation: AI reads demo.md, executes all steps, operates the system,
      narrates to user. `telec todo demo` runs code blocks for validation.
- [ ] Keep five acts narrative in snapshot.json — that's the delivery story, not the demo
- [ ] Update builder guidance: demo.md is part of definition of done
- [ ] Add heuristic: CLI change → run command in demo, TUI change → operate TUI,
      web UI → Playwright, messaging → trigger via API

### Task 3.3: Update demo artifact spec

**File:** `docs/project/spec/demo-artifact.md`

- [ ] Add `demo.md` as the primary demonstration artifact
- [ ] Drop `demo` field from snapshot.json schema (mark deprecated, keep backward compat note)
- [ ] Document code block extraction convention (fenced bash = executable)
- [ ] Document `<!-- skip-demo -->` escape hatch

### Task 3.4: Update lifecycle overview

**File:** `docs/global/software-development/procedure/lifecycle-overview.md`

- [ ] Fix demo phase description: drop "demo.sh" and "widget" references
- [ ] Output is `demos/{slug}/` with `snapshot.json` and `demo.md`
- [ ] Responsibility stays Orchestrator (triggers), but presenter AI executes

## Phase 4: Todo scaffold and prepare integration

### Task 4.1: Add demo.md to todo scaffold

**File:** `teleclaude/todo_scaffold.py`

- [ ] Add `demo.md` template to the scaffold
- [ ] Template content: heading + placeholder for architect to fill during prepare

**File:** `templates/todos/demo.md`

- [ ] Create template: `# Demo: {slug}\n\n<!-- Draft demo steps during prepare. Refine during build. -->\n`

### Task 4.2: Update prepare-draft guidance

**File:** `agents/commands/next-prepare-draft.md` (or the procedure doc it references)

- [ ] Add demo.md drafting as a prepare-draft artifact
- [ ] Architect defines: what medium is the delivery shown in? What does the user
      observe? What commands validate it works?
- [ ] Draft doesn't need to be perfect — builder refines

## Phase 5: Validation

- [ ] `telec todo demo themed-primary-color` exits 0 (code blocks pass)
- [ ] `telec todo demo tui-markdown-editor` exits 0
- [ ] `telec todo create test-demo-scaffold && ls todos/test-demo-scaffold/demo.md`
      confirms scaffold includes demo.md (clean up after)
- [ ] Review all updated docs for internal consistency
- [ ] `make lint`
