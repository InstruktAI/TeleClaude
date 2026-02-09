---
id: 'general/procedure/maintenance/merge-runner'
type: 'procedure'
domain: 'software-development'
scope: 'project'
description: 'Serialized merge procedure that promotes approved worktree branches into main through an isolated merge workspace.'
---

# Merge Runner — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@docs/project/spec/jobs/merge-runner.md

## Goal

Promote ready work into `main` with one serialized merge path so parallel workers
can never race each other when integrating changes.

This procedure is merge-only. It does not perform feature implementation,
planning, or review work.

## Preconditions

1. The runner is executing as the `merge-runner` job.
2. Merge execution happens in an isolated merge worktree (not the user's active main workspace).
3. A todo is merge-eligible only when its synced `todos/{slug}/state.json` satisfies:
   - `build == complete`
   - `review == approved`
   - `docstrings == complete`
   - `snippets == complete`
   - `deferrals_processed == true` when deferrals are present.
4. Only one merge operation runs at a time.

## Steps

1. Discover merge candidates from roadmap and state files:
   - candidate slugs must still be active (not delivered, not icebox),
   - candidate state must satisfy the merge-eligible predicate.
2. Acquire the merge lock.
3. In the isolated merge worktree:
   - checkout and update `main`,
   - for each candidate in deterministic order, merge `slug` branch into `main`,
   - stop immediately on first conflict.
4. On each successful merge:
   - update roadmap marker for the slug to done (`[x]`),
   - append delivery record to `todos/delivered.md`,
   - persist any merge report artifacts defined by project process.
5. Release the merge lock.
6. Write run report with merged slugs, skipped slugs, and blocking errors.

## Outputs

- Serialized merge execution (no concurrent merge writers to `main`).
- Updated `todos/roadmap.md` for merged slugs.
- Updated `todos/delivered.md` entries for merged slugs.
- Job run report under `~/.teleclaude/jobs/merge-runner/runs/`.

## Recovery

1. If lock acquisition fails, exit cleanly and retry next schedule tick.
2. If merge conflict occurs:
   - stop further merges,
   - record conflicting slug and conflict summary,
   - keep remaining candidates queued for future runs.
3. If a candidate no longer satisfies merge-eligible state at run time, skip and log reason.
