# Requirements: bug-delivery-service

## Goal

Enable fire-and-forget bug fixing: a single CLI command (`telec bugs report`) captures a bug, scaffolds a todo, creates a branch and worktree, and dispatches an autonomous orchestrator that investigates, fixes, reviews, and merges — no human in the loop until the PR lands.

## Problem

Bugs discovered during ad-hoc AI-assisted development have no fast capture-and-fix mechanism. The current binary — fix inline or promote to a full todo — is too coarse. Inline fixing derails current work. Full todo promotion requires prepare-phase ceremony (requirements, DOR gate, roadmap entry) that is overkill for a straightforward bug.

## In Scope

1. **CLI intake** — `telec bugs report <description> [--slug <slug>]` creates a bug todo, branch, worktree, and dispatches an orchestrator.
2. **CLI listing** — `telec bugs list` shows in-flight bug fixes with status.
3. **Bug scaffold** — `create_bug_skeleton()` in `todo_scaffold.py` creates `bug.md` + `state.yaml` (no prepare artifacts).
4. **Bug template** — `templates/todos/bug.md` with Symptom, Discovery Context, Investigation, Root Cause, Fix Applied sections.
5. **State machine bypass** — `next_work()` detects `bug.md`, skips roadmap/DOR/prepare gates, dispatches `next-bugs-fix` worker instead of `next-build`.
6. **Bug fix worker command** — `agents/commands/next-bugs-fix.md` loads systematic-debugging skill, uses `bug.md` as requirement.
7. **Review adaptation** — `next-review` accepts `bug.md` as requirement source when `requirements.md` is absent.
8. **Finalize adaptation** — bug finalize deletes todo directory (no `delivered.md` entry).
9. **Orchestrator dispatch** — `telec bugs report` dispatches a session that calls `next_work(slug)` in a loop until finalize completes.

## Out of Scope

- Bug triage / prioritization (bugs are always immediate).
- Bug reporting from within agent sessions (manual `telec bugs report` only).
- Bug metrics / dashboards.
- Automatic reproduction steps.

## Success Criteria

- [ ] `telec bugs report "session hook fires twice"` creates `todos/fix-session-hook-fires-twice/bug.md` + `state.yaml`, creates worktree, dispatches orchestrator.
- [ ] `telec bugs list` shows the bug with its current status (pending/building/reviewing/approved).
- [ ] `next_work(slug="fix-session-hook-fires-twice")` detects `bug.md`, skips roadmap/DOR gates, dispatches `next-bugs-fix`.
- [ ] Fix worker fills in `bug.md` Investigation/Root Cause/Fix Applied sections, commits fix.
- [ ] Reviewer validates fix against `bug.md` symptom and root cause.
- [ ] Finalize merges PR and deletes `todos/fix-*` directory entirely (no delivery log).
- [ ] All existing tests pass. New unit tests cover bug scaffold and bug detection.
- [ ] `make lint` passes.

## Constraints

- Bugs use `state.yaml` (not `state.json`) — matching the project's existing format.
- Bug state starts at `phase: in_progress, build: pending` (skips `pending` and `ready` phases).
- Bugs are NOT roadmap items — they live in `todos/` for state tracking only.
- Bug slugs follow the pattern `fix-{descriptive-name}`.
- The `bug.md` file presence is the discriminator — no schema changes to `TodoState`.
- The `next_work()` state machine flow (build → review → fix-review → finalize) is unchanged. Only the entry gate and worker command differ.

## Risks

- State machine modifications touch `core.py` which is a high-traffic file — careful to avoid regression.
- Orchestrator dispatch from CLI introduces async dependency on daemon availability.
