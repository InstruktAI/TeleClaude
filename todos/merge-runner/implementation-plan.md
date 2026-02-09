# Implementation Plan: merge-runner

## Approach

Create a merge-only maintenance flow that reuses existing roadmap/state signals,
adds a serialized merge execution path, and runs on periodic schedule as an
agent job.

## Group 1: Job and process contract

- [ ] Add merge runner job spec at `docs/project/spec/jobs/merge-runner.md`.
- [ ] Add merge runner procedure at `docs/global/general/procedure/maintenance/merge-runner.md`.
- [ ] Register scheduler entry in `teleclaude.yml` for 10-minute interval execution.

## Group 2: Merge readiness and candidate discovery

- [ ] Implement candidate selection from roadmap + `todos/{slug}/state.json` merge gate.
- [ ] Exclude slugs from delivered and icebox.
- [ ] Define deterministic processing order.

## Group 3: Serialized merge execution

- [ ] Implement single-writer lock for merge execution.
- [ ] Execute merges in isolated merge worktree.
- [ ] Stop on first conflict and persist conflict diagnostics.

## Group 4: Post-merge bookkeeping

- [ ] Mark merged slug done in roadmap.
- [ ] Append merged slug to delivered log.
- [ ] Write run report artifact with merged/skipped/failed details.

## Verification

- [ ] Simulate two eligible slugs and verify serialized merge behavior.
- [ ] Simulate merge conflict and verify early stop + report.
- [ ] Verify no stash usage in merge path.
