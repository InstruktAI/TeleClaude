# Implementation Plan: fix-demo-runner

## Overview

Redesign the demo system around `demo.md` — a freeform markdown artifact with
executable code blocks and guided steps. The demo validator (`telec todo demo`)
becomes a build gate. Touches the CLI runner, build procedure, command artifact,
procedure docs, spec docs, todo scaffold, and existing demos. No MCP changes.

## Phase 1: Demo validator — CLI runner rewrite

### Task 1.1: Update `_handle_todo_demo` to prefer demo.md

**File:** `teleclaude/cli/telec.py`

- [x] When running a demo with slug: look for `demo.md` in two locations: 1. `todos/{slug}/demo.md` (during build, before delivery) 2. `demos/{slug}/demo.md` (after delivery)
      Fall back to `snapshot.json` `demo` field for backward compatibility
- [x] If `demo.md` exists: extract all fenced ```bash code blocks
- [x] Execute each block sequentially via `subprocess.run(block, shell=True, cwd=project_root)`
- [x] Report per-block pass/fail with the block content as context
- [x] Exit 0 only if all blocks pass, exit 1 on first failure
- [x] If no code blocks found but demo.md exists: exit 0 with note
      "Demo has guided steps only (no executable blocks)"
- [x] Keep the listing mode (`telec todo demo` with no slug) unchanged — it reads
      snapshot.json for title/version/date

### Task 1.2: Code block extraction utility

**File:** `teleclaude/cli/telec.py` (inline, no separate module)

- [x] Simple regex: extract content between ` ```bash ` and ` ``` ` fences
- [x] Skip blocks preceded by `<!-- skip-validation: reason -->` comment
- [x] Return list of (line_number, block_content, skipped) tuples for reporting
- [x] Report skipped blocks with their reason (visibility, not silence)

## Phase 2: Write demo.md for existing demos

### Task 2.1: themed-primary-color demo.md

**File:** `demos/themed-primary-color/demo.md`

- [x] Executable: verify theme module loads and contains expected theme names
- [x] Executable: verify theme CSS classes or color values are present
- [x] Guided: describe the visual experience — warm orange at agent level,
      peaceful gray at level 0, how to toggle via carousel
- [x] Guided: tell the presenter to launch telec and navigate to show the themes

### Task 2.2: tui-markdown-editor demo.md

**File:** `demos/tui-markdown-editor/demo.md`

- [x] Executable: verify editor module is importable and entry point exists
- [x] Executable: verify the editor can be invoked with --help or similar
- [x] Guided: describe launching the editor via 'e' key in preparation view,
      markdown syntax highlighting, save/cancel behavior
- [x] Guided: tell the presenter to launch telec and operate the editor

## Phase 3: Build gate integration

### Task 3.1: Update build procedure

**File:** `docs/global/software-development/procedure/lifecycle/build.md`

- [ ] Add demo validation as a pre-completion step (after tests, before clean tree check):
      "Run `telec todo demo {slug}`. All code blocks must exit 0."
- [ ] Add escape hatch: "If demo.md has no executable blocks or the delivery
      cannot be demonstrated, note the exception in demo.md with reasoning."

### Task 3.2: Update quality checklist template

**File:** `templates/todos/quality-checklist.md`

- [ ] Make the "Demo is runnable and verified" gate more specific:
      "Demo validated (`telec todo demo {slug}` exits 0, or exception noted)"

## Phase 4: Command artifact and docs

### Task 4.1: Rewrite /next-demo command

**File:** `agents/commands/next-demo.md`

- [ ] Purpose: conversational presenter that reads `demo.md` and walks the user through
- [ ] No slug: list available demos (via `telec todo demo`), ask which to present
- [ ] With slug: read `demos/{slug}/demo.md`, execute steps sequentially
- [ ] For code blocks: run via Bash, show output to user, narrate results
- [ ] For guided steps: operate the system (TUI keys, CLI, API) and narrate
- [ ] For verification: check assertions, report pass/fail to user
- [ ] On failure: offer to run `telec bugs report` with the failure context
- [ ] After successful demo: read `snapshot.json` and celebrate with the five acts
      narrative — conversationally, not as a fixed widget
- [ ] Drop all render_widget/celebration-widget references

### Task 4.2: Update demo procedure doc

**File:** `docs/global/software-development/procedure/lifecycle/demo.md`

- [ ] Replace "The demo field" section with demo.md framework description
- [ ] Creation lifecycle: architect drafts in prepare (how to prove it works),
      builder refines with real implementation knowledge in build
- [ ] Demo validator: `telec todo demo` extracts code blocks, runs them, build gate
- [ ] Presentation: AI reads demo.md, executes all steps, operates the system,
      narrates to user
- [ ] Testability default: almost everything should have executable code blocks.
      The AI can spin up its own TUI instance, run Playwright, start sessions.
      `<!-- skip-validation: reason -->` for the rare exception.
- [ ] Non-destructive rule: demos run on real data, never destructive. CRUD demos
      create their own test data and clean up. Builder writes with this awareness.
- [ ] Bug fixes get demos too: reproduce the fix scenario, show it's gone
- [ ] Escape hatch: if entire delivery can't be demonstrated, note exception,
      reviewer accepts or pushes back
- [ ] Keep five acts narrative in snapshot.json — that's the delivery story
- [ ] Update builder guidance: demo validation is part of definition of done
- [ ] Heuristic guidance (not prescriptive):
      CLI change → run command, TUI change → spin up own TUI and operate it,
      web UI → Playwright, messaging → trigger via API

### Task 4.3: Update demo artifact spec

**File:** `docs/project/spec/demo-artifact.md`

- [ ] Add `demo.md` as the primary demonstration artifact
- [ ] Drop `demo` field from snapshot.json schema (mark deprecated, keep backward compat note)
- [ ] Document code block extraction convention (fenced bash = executable)
- [ ] Document `<!-- skip-validation: reason -->` annotation for individual blocks
- [ ] Document non-destructive rule (create own test data, clean up after)

### Task 4.4: Update lifecycle overview

**File:** `docs/global/software-development/procedure/lifecycle-overview.md`

- [ ] Fix demo phase description: drop "demo.sh" and "widget" references
- [ ] Output is `demos/{slug}/` with `snapshot.json` and `demo.md`
- [ ] Clarify: demo validation happens during build (gate), demo presentation
      happens after delivery (celebration)

## Phase 5: Todo scaffold and prepare integration

### Task 5.1: Add demo.md to todo scaffold

**File:** `teleclaude/todo_scaffold.py`

- [ ] Add `demo.md` template to the scaffold
- [ ] Update docstring to reflect 6 files

**File:** `templates/todos/demo.md`

- [ ] Create template with heading and placeholder for architect

### Task 5.2: Update prepare-draft guidance

**File:** The prepare-draft procedure doc or command artifact that references it

- [ ] Add demo.md drafting as a prepare-draft artifact
- [ ] Architect defines: what medium is the delivery shown in? What does the user
      observe? What commands validate it works?
- [ ] Draft doesn't need to be perfect — builder refines

## Phase 6: Validation

- [ ] `telec todo demo themed-primary-color` exits 0 (code blocks pass)
- [ ] `telec todo demo tui-markdown-editor` exits 0
- [ ] `telec todo create test-demo-scaffold` → `todos/test-demo-scaffold/demo.md` exists
      (clean up after)
- [ ] Review all updated docs for internal consistency
- [ ] `make lint`
