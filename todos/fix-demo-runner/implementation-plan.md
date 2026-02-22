# Implementation Plan: fix-demo-runner

## Overview

Redesign the demo system around `demo.md` — a freeform markdown artifact with
executable code blocks and guided steps. The demo validator (`telec todo demo`)
becomes a build gate. Touches the CLI runner, four doc snippets (procedure, spec,
two procedure updates), one command artifact, the todo scaffold, and existing demos.
No MCP changes.

**Authoring order matters.** Doc snippets are written in dependency order: the demo
procedure is the authoritative foundation, the spec defines the artifact format,
then the command artifact is derived from the procedure's presentation section.
Run `telec sync` after all doc and artifact changes.

## Phase 1: Demo validator — CLI runner rewrite

### Task 1.1: Update `_handle_todo_demo` to prefer demo.md

**File:** `teleclaude/cli/telec.py`

- [ ] When running a demo with slug: look for `demo.md` in two locations: 1. `todos/{slug}/demo.md` (during build, before delivery) 2. `demos/{slug}/demo.md` (after delivery)
      Fall back to `snapshot.json` `demo` field for backward compatibility
- [ ] If `demo.md` exists: extract all fenced ```bash code blocks
- [ ] Execute each block sequentially via `subprocess.run(block, shell=True, cwd=project_root)`
- [ ] Report per-block pass/fail with the block content as context
- [ ] Exit 0 only if all blocks pass, exit 1 on first failure
- [ ] If no code blocks found but demo.md exists: exit 0 with note
      "Demo has guided steps only (no executable blocks)"
- [ ] Keep the listing mode (`telec todo demo` with no slug) unchanged — it reads
      snapshot.json for title/version/date

### Task 1.2: Code block extraction utility

**File:** `teleclaude/cli/telec.py` (inline, no separate module)

- [ ] Simple regex: extract content between ` ```bash ` and ` ``` ` fences
- [ ] Return list of (line_number, block_content) tuples for reporting

## Phase 2: Doc snippets — taxonomy layer

Written in dependency order. Each snippet follows its taxonomy's required sections.

### Task 2.1: Rewrite demo procedure doc (foundation)

**File:** `docs/global/software-development/procedure/lifecycle/demo.md`
**Taxonomy:** procedure (Goal, Preconditions, Steps, Outputs, Recovery)

This is the authoritative document. Everything else derives from it. Full rewrite
covering three concerns:

- [ ] **Goal:** Demonstrate every delivery via AI-operated, testable demonstrations.
      Demo validation is a build gate. Demo presentation celebrates delivery.
- [ ] **Preconditions:** demo.md exists in todo or demos folder, snapshot.json for
      delivery narrative
- [ ] **Steps — Creation lifecycle:** - Architect drafts `demo.md` during prepare (what to prove, how to validate) - Builder refines during build with implementation knowledge (real commands,
      real assertions) - Builder copies `demo.md` to `demos/{slug}/` alongside `snapshot.json`
- [ ] **Steps — Validation (build gate):** - `telec todo demo <slug>` extracts fenced bash code blocks, runs them - All blocks must exit 0 — this is a build gate - Builder runs validation before reporting build complete
- [ ] **Steps — Presentation:** - AI reads `demo.md` and executes ALL steps — code blocks, guided steps,
      verification - AI is the operator: runs commands, operates TUI, drives Playwright, calls APIs - User watches; AI narrates - Five acts narrative from `snapshot.json` woven into conversation
- [ ] **Testability default:** almost everything should have executable code blocks.
      AI can spin up own TUI instance, run Playwright, start sessions.
      "Not automatable" is the rare exception, not the default.
- [ ] **Non-destructive rule:** demos run on real data, never destructive. CRUD demos
      create own test data and clean up. Builder writes with this awareness.
- [ ] **Bug fixes get demos too:** reproduce the fix scenario, show it's gone.
- [ ] **Escape hatch:** if entire delivery can't produce executable demo steps
      (pure refactors with no observable change), builder notes exception in
      demo.md with reasoning. Reviewer accepts or pushes back.
- [ ] **Heuristic guidance** (not prescriptive):
      CLI change -> run command, TUI change -> spin up own TUI and operate it,
      web UI -> Playwright, messaging -> trigger via API
- [ ] **Builder guidance:** demo validation is part of definition of done.
      demo.md is part of the committed build output.
- [ ] **Outputs:** `demos/{slug}/` with `snapshot.json` and `demo.md`
- [ ] **Recovery:** backward compat with `demo` field when demo.md absent.
      Semver gate disables stale demos on breaking version bumps.

### Task 2.2: Update demo artifact spec

**File:** `docs/project/spec/demo-artifact.md`
**Taxonomy:** spec (What it is, Canonical fields, Known caveats)

- [ ] Add `demo.md` as the primary demonstration artifact alongside `snapshot.json`
- [ ] Document `demo.md` conventions: fenced bash blocks are executable by the
      CLI validator, everything else is guided presentation for the AI
- [ ] Deprecate `demo` field in snapshot.json schema (keep backward compat note,
      mark as deprecated)
- [ ] Document non-destructive rule (create own test data, clean up after)
- [ ] Update Known caveats for demo.md backward compatibility

### Task 2.3: Update build procedure — add demo validation gate

**File:** `docs/global/software-development/procedure/lifecycle/build.md`
**Taxonomy:** procedure (updating existing Steps and Pre-completion checklist)

- [ ] Add demo validation to the Pre-completion checklist (after tests, before
      clean tree check):
      "Run `telec todo demo {slug}`. All code blocks must exit 0."
- [ ] Add escape hatch note: "If demo.md has no executable blocks or the delivery
      cannot be demonstrated, note the exception in demo.md with reasoning."

### Task 2.4: Update lifecycle overview

**File:** `docs/global/software-development/procedure/lifecycle-overview.md`
**Taxonomy:** procedure (updating existing section 6)

- [ ] Fix demo phase description: drop "demo.sh" and "widget" references
- [ ] Output is `demos/{slug}/` with `snapshot.json` and `demo.md`
- [ ] Clarify: demo validation happens during build (gate), demo presentation
      happens after delivery (celebration)

## Phase 3: Command artifact — derived from procedure

### Task 3.1: Rewrite /next-demo command

**File:** `agents/commands/next-demo.md`
**Schema:** command artifact (frontmatter, activation line, Required reads, Purpose,
Inputs, Outputs, Steps)

The command wraps the presentation section of the demo procedure.

- [ ] **Required reads:** `@~/.teleclaude/docs/software-development/procedure/lifecycle/demo.md`
- [ ] **Activation line:** "You are now the Demo Presenter."
- [ ] **Purpose:** conversational presenter that reads `demo.md` and walks the user
      through the demonstration, operating the system and narrating
- [ ] **Inputs:** optional slug via $ARGUMENTS
- [ ] **Outputs:** - No slug: list available demos, ask which to present - With slug: full demo execution with narration
- [ ] **Steps — No slug:** list available demos via `telec todo demo`, ask which
      to present
- [ ] **Steps — With slug:** - Read `demos/{slug}/demo.md` - Execute steps sequentially: run code blocks via Bash showing output,
      follow guided steps by operating the system (TUI keys, CLI, API, Playwright),
      check verification assertions - Narrate throughout — the user watches, the AI operates - On failure: offer to run `telec bugs report` with the failure context - After successful demo: read `demos/{slug}/snapshot.json` and celebrate with
      the five acts narrative — conversationally, not as a fixed widget
- [ ] Drop all render_widget/celebration-widget references

## Phase 4: Write demo.md for existing demos

### Task 4.1: themed-primary-color demo.md

**File:** `demos/themed-primary-color/demo.md`

- [ ] Executable: verify theme module loads and contains expected theme names
- [ ] Executable: verify theme CSS classes or color values are present
- [ ] Guided: describe the visual experience — warm orange at agent level,
      peaceful gray at level 0, how to toggle via carousel
- [ ] Guided: tell the presenter to launch telec and navigate to show the themes

### Task 4.2: tui-markdown-editor demo.md

**File:** `demos/tui-markdown-editor/demo.md`

- [ ] Executable: verify editor module is importable and entry point exists
- [ ] Executable: verify the editor can be invoked with --help or similar
- [ ] Guided: describe launching the editor via 'e' key in preparation view,
      markdown syntax highlighting, save/cancel behavior
- [ ] Guided: tell the presenter to launch telec and operate the editor

## Phase 5: Todo scaffold and prepare integration

### Task 5.1: Add demo.md to todo scaffold

**File:** `teleclaude/todo_scaffold.py`

- [ ] Add `demo.md` template to the scaffold
- [ ] Update docstring to reflect 6 files

**File:** `templates/todos/demo.md`

- [ ] Create template with heading and placeholder for architect to define
      what medium the delivery is shown in, what the user observes, and what
      commands validate it works

### Task 5.2: Update quality checklist template

**File:** `templates/todos/quality-checklist.md`

- [ ] Make the "Demo is runnable and verified" gate more specific:
      "Demo validated (`telec todo demo {slug}` exits 0, or exception noted)"

### Task 5.3: Update prepare-draft procedure

**File:** `docs/global/software-development/procedure/lifecycle/prepare/`
(whichever sub-procedure covers artifact drafting)

- [ ] Add demo.md drafting as a prepare-phase artifact
- [ ] Architect defines: what medium is the delivery shown in? What does the user
      observe? What commands validate it works?
- [ ] Draft doesn't need to be perfect — builder refines

## Phase 6: Sync and validation

- [ ] Run `telec sync` to deploy all doc and artifact changes
- [ ] `telec todo demo themed-primary-color` exits 0 (code blocks pass)
- [ ] `telec todo demo tui-markdown-editor` exits 0
- [ ] `telec todo create test-demo-scaffold` -> `todos/test-demo-scaffold/demo.md` exists
      (clean up after)
- [ ] Review all updated docs for internal consistency
- [ ] `make lint`
