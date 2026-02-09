# Requirements: merge-runner

## Goal

Introduce a serialized merge runner that is solely responsible for integrating
approved worktree branches into `main` so concurrent worker completions never
race on integration.

## Functional requirements

1. Merge readiness is derived from existing state files (`todos/{slug}/state.json`), not ad-hoc flags.
2. Merge runner processes only active slugs and skips delivered/icebox entries.
3. Merge runner executes merges in deterministic order, one at a time.
4. Merge runner stops on first merge conflict and records actionable diagnostics.
5. Successful merges update roadmap status and delivered log.
6. Merge operations run in isolated merge workspace and must not mutate the user's active main working tree.

## Non-functional requirements

1. Idempotent periodic execution (safe at least hourly; safe for future sub-hour cadence).
2. No fallback stash logic in the merge path.
3. Clear run report artifact with merged/skipped/failed outcomes.

## Acceptance criteria

1. Two merge-eligible slugs are never merged concurrently.
2. Runner can merge one eligible slug and mark it delivered without touching user active workspace.
3. On conflict, runner stops further merges and reports the blocking slug.
4. Re-running after conflict resolution resumes from remaining candidates.
