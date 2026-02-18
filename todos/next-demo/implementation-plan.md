# Implementation Plan: next-demo

## Overview

The demo system has four parts: artifact storage, the command that composes demos, orchestration wiring that triggers it, and docs that formalize it. The command is the core — it reads from todo artifacts and git, writes a structured markdown file, and optionally renders it as a widget. The orchestration change is minimal: one new step in the state machine between finalize and cleanup.

---

## Phase 1: Artifact Storage & Format

### Task 1.1: Create `demos/` directory and format spec

**File(s):** `demos/.gitkeep`, `docs/project/spec/demo-artifact.md`

- [ ] Create `demos/` directory at repository root
- [ ] Write a doc snippet (`project/spec/demo-artifact`) defining the artifact schema: YAML frontmatter (slug, title, delivered, commit, metrics object) + five-act markdown body
- [ ] Add `demos/` to `.gitignore` exclusions if needed (demos should be committed)

---

## Phase 2: `/next-demo` Command

### Task 2.1: Create the command artifact

**File(s):** `agents/commands/next-demo.md`

- [ ] Create `/next-demo` command following the agent artifact schema
- [ ] Required reads: `software-development/procedure/lifecycle/demo`, `project/spec/demo-artifact`
- [ ] Input: slug (from `$ARGUMENTS`)
- [ ] Steps:
  1. Read todo artifacts: `requirements.md`, `implementation-plan.md`, `review-findings.md`, `quality-checklist.md`, `state.json`
  2. Run git commands for metrics: `git log --oneline main..{slug}` for commit count, `git diff --stat main..{slug}` for file/line stats, `git diff --diff-filter=A --name-only main..{slug}` for new files
  3. Read `todos/delivered.md` for title and date
  4. Compose the five acts from the gathered data
  5. Write demo artifact to `demos/{slug}.md`
  6. Render via `teleclaude__render_widget` with success status, five sections, metrics table
  7. Commit the demo artifact
- [ ] Output format: `DEMO COMPLETE: {slug}\nArtifact: demos/{slug}.md\nWidget: rendered`

### Task 2.2: Tone and content guidance in the command

**File(s):** `agents/commands/next-demo.md`

- [ ] Act 1 (Challenge): One paragraph, no jargon, user's perspective. Read from `requirements.md` Goal section.
- [ ] Act 2 (Build): Highlight the most interesting technical choice. Read from `implementation-plan.md` overview + git diff stat.
- [ ] Act 3 (Gauntlet): Frame review as quality earned. Read from `review-findings.md` — count criticals found/fixed, rounds survived.
- [ ] Act 4 (Numbers): Metrics table, scannable at a glance. All numbers from git + state.json.
- [ ] Act 5 (What's Next): Non-blocking suggestions from review findings. Ideas for future work.
- [ ] Tone: celebratory but specific. Let the numbers speak. No fluff.

---

## Phase 3: Orchestration Wiring

### Task 3.1: Add demo step to `next_work` state machine

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] After the finalize dispatch block (step 9, ~line 1913), add a demo step:
  - When finalize completes and the orchestrator is about to clean up, first check if `demos/{slug}.md` exists
  - If not, dispatch `/next-demo {slug}` (inline or as a lightweight command)
  - The demo runs in the worktree context (artifacts still on disk)
  - After demo completes, proceed to cleanup
- [ ] Add `"next-demo"` to the `PHASE_COMMANDS` or equivalent dispatch config
- [ ] The demo step should be non-blocking: if it fails, log a warning and proceed to cleanup (don't block delivery on a failed celebration)

### Task 3.2: Update finalize completion handler in state machine output

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] In the `"next-finalize"` completion instructions template (~line 143), insert the demo step between "verify merge" and "CLEANUP":
  ```
  WHEN WORKER COMPLETES:
  1. Verify merge succeeded and delivery log updated
  2. If success:
     - teleclaude__end_session(...)
     - DEMO (run before cleanup, while artifacts exist):
       teleclaude__run_agent_command(command="/next-demo", args="{slug}", ...)
     - CLEANUP (orchestrator-owned, run from main repo):
       ...
  ```

---

## Phase 4: Documentation Updates

### Task 4.1: Update demo procedure doc — artifact storage

**File(s):** `docs/global/software-development/procedure/lifecycle/demo.md`

- [ ] Replace step 4 (Archive) which currently says "no separate artifact needed" with:
  - Write demo artifact to `demos/{slug}.md` with YAML frontmatter + five-act body
  - Commit the artifact before cleanup removes the source data
  - The artifact is the durable record; `delivered.md` is the index

### Task 4.2: Update lifecycle overview — add Demo phase

**File(s):** `docs/global/software-development/procedure/lifecycle-overview.md`

- [ ] Add Demo as phase 5.5 between Finalize and Maintenance:
  ```
  1. Prepare
  2. Build
  3. Review
  4. Fix
  5. Finalize
  6. Demo
  7. Maintenance
  ```
- [ ] Add a section describing the Demo phase: output is `demos/{slug}.md`, responsibility is Orchestrator (inline) or Demo Agent, triggered automatically after finalize

### Task 4.3: Sync index after doc changes

**File(s):** `docs/global/index.yaml`

- [ ] Run `telec sync` to update the snippet index with any new or modified docs

---

## Phase 5: Widget Rendering

### Task 5.1: Demo widget composition logic

**File(s):** `agents/commands/next-demo.md` (rendering section)

- [ ] Define the `render_widget` expression structure for demos:
  - `title`: "🎉 {title}" (or project-appropriate)
  - `status`: "success"
  - `sections`:
    - `text` section for each act (Act 1–3, 5)
    - `table` section for Act 4 (metrics)
    - `divider` between acts
    - `code` section if a specific technical decision deserves highlighting
  - `footer`: merge commit hash + delivery date
- [ ] The widget is rendered to the orchestrator's session (the user watching the pipeline)
- [ ] The markdown artifact in `demos/{slug}.md` is the durable version; the widget is the live presentation

---

## Phase 6: Validation

### Task 6.1: Tests

- [ ] Test that demo artifact format matches the spec (YAML frontmatter + five acts)
- [ ] Test that the state machine includes the demo step after finalize
- [ ] Test graceful degradation: demo failure does not block cleanup
- [ ] Run `make test`

### Task 6.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Verify demo procedure doc and lifecycle overview are consistent

---

## Phase 7: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly
