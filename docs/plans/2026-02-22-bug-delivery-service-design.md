# Bug Delivery Service — Design

## Problem

Bugs discovered during ad-hoc AI-assisted development have no fast capture-and-fix
mechanism. The current binary — fix inline or promote to a full todo — is too coarse.
Inline fixing derails current work. Full todo promotion is too much ceremony mid-flow.
Bugs fall through the cracks.

## Solution

A fire-and-forget bug pipeline: one CLI command captures the bug, dispatches an
autonomous orchestrator that fixes, reviews, and merges — no human in the loop until
the PR lands.

## Design

### CLI Surface

```
telec bugs report <description> [--slug <slug>]   # Intake + fire
telec bugs list                                     # In-flight bugs only
```

`report` captures the bug, scaffolds a todo, creates a branch and worktree, and
dispatches an orchestrator. `list` shows only active bugs — completed bugs are deleted.

### File-Based Bug Signal

A `bug.md` file in a todo directory signals that the item is a bug. Its presence is the
discriminator — no schema changes to `state.json`, no new status fields.

**Directory structure:**

```
todos/fix-{slug}/
  bug.md          # Structured bug report (the requirement)
  state.json      # Starts at build phase (skips prepare)
```

**bug.md template:**

```markdown
# Bug: {description}

## Symptom

{description}

## Discovery Context

Reported by: {agent/user}
Session: {session_id or "manual"}
Date: {ISO8601}

## Investigation

<!-- Fix worker fills this -->

## Root Cause

<!-- Fix worker fills this -->

## Fix Applied

<!-- Fix worker fills this -->
```

The worker fills Investigation, Root Cause, and Fix Applied during its work. The file
serves as both intake form and investigation log.

**state.json — skips prepare:**

```json
{
  "phase": "in_progress",
  "build": "pending",
  "review": "pending",
  "schema_version": 1
}
```

No DOR, no breakdown, no prepare artifacts.

### Bugs Are Not Roadmap Items

Bugs do not appear in `roadmap.yaml`. They are reactive work that lives in `todos/`
for state tracking only. Visibility comes through:

- `telec bugs list` — scans for `bug.md` files, shows status from `state.json`
- TUI sessions view — orchestrator and worker sessions appear naturally

### Pipeline: Orchestrator Per Bug

```
telec bugs report "session hook fires twice on reconnect"
  |
  +-- creates todos/fix-session-hook-double-fire/
  |     bug.md + state.json
  +-- creates branch fix/session-hook-double-fire from main
  +-- creates worktree at trees/fix-session-hook-double-fire
  +-- dispatches ONE orchestrator session
        |
        +-- calls next_work(slug)
        |     sees bug.md + build: pending
        |     dispatches fix worker (loads systematic-debugging skill)
        |
        +-- fix worker:
        |     investigates, fills bug.md sections
        |     fixes, commits
        |     creates PR fix/session-hook-double-fire -> main
        |     marks build: complete
        |
        +-- calls next_work(slug)
        |     dispatches review worker (standard next-review)
        |     reviewer validates fix against bug.md
        |     writes review-findings.md, sets verdict
        |
        +-- if changes_requested:
        |     calls next_work -> fix-review -> re-review
        |     (up to max_review_rounds)
        |
        +-- if approved:
        |     calls next_work -> finalize
        |     merges PR
        |     deletes todos/fix-session-hook-double-fire/ entirely
        |     notifies user
        |
        +-- orchestrator exits
```

### Differences From Normal Todo Orchestration

| Aspect             | Normal Todo                                 | Bug                              |
| ------------------ | ------------------------------------------- | -------------------------------- |
| Intake             | `input.md` + prepare phase                  | `bug.md`, no prepare             |
| Roadmap            | Added to `roadmap.yaml`                     | Not in roadmap                   |
| Requirement source | `requirements.md`                           | `bug.md`                         |
| Build worker       | Standard build, follows implementation plan | Fix worker, loads debugger skill |
| Finalize           | Moves to `delivered.yaml`                   | Deletes todo directory           |
| Visibility         | Roadmap + sessions                          | `telec bugs list` + sessions     |

### What Changes

**New:**

- `telec bugs report` CLI command (intake + dispatch)
- `telec bugs list` CLI command (list in-flight bugs)
- `bug.md` template
- Bug dispatcher (scaffold + branch + worktree + orchestrator launch)

**Modified:**

- `next-work` state machine: detect `bug.md`, skip prepare, route to fix worker
- Fix worker instructions: load systematic-debugging skill, use `bug.md` as requirement
- Review worker: accept `bug.md` as requirement source when `requirements.md` absent
- Finalize: when `bug.md` exists, delete todo directory instead of archiving

**Unchanged:**

- State machine phases (build -> review -> fix-review -> finalize)
- Worker dispatch/cleanup lifecycle
- PR creation flow
- Session visibility in TUI

### Completed Bug Lifecycle

Done bugs are deleted entirely. No `delivered.yaml` entry, no archive. The merged PR
in git is the only record. Fix forward, don't look back.

### telec bugs list Output

```
fix-session-hook-double-fire   building    2m ago
fix-cache-ttl-overflow         reviewing   8m ago
fix-widget-render-crash        approved    1h ago   PR #47
```

Shows only in-flight work. Once merged and deleted, gone from the list.
