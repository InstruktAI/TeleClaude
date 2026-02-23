# Requirements: lifecycle-enforcement-gates

## Goal

Replace the trust-based lifecycle model with an evidence-based one. The state machine must run build gates (tests, demo validation) and enforce their results — not trust the builder's self-reported checklist. The quality checklist becomes a receipt of what the machine verified, not a self-reported promise.

## Scope

### In scope

1. **`telec todo demo` subcommand refactor** — Split the current monolithic demo runner into three explicit subcommands: `validate`, `run`, `create`.
2. **Silent-pass bug fix** — `telec todo demo` currently exits 0 when demo.md has no executable blocks. Must exit 1 (unfilled template = validation failure).
3. **`<!-- no-demo: reason -->` escape hatch** — Document-level marker that `validate` respects (exit 0, logs reason). For non-demonstrable deliveries.
4. **State machine build gates in `next_work()`** — After build is marked complete, `next_work` runs `make test` and `telec todo demo validate {slug}` in the worktree. If either fails, reset build to `started` and instruct orchestrator to message the builder. Builder session stays alive.
5. **POST_COMPLETION flow change** — The `next-build` POST_COMPLETION instructions must change: orchestrator calls `mark_phase(build=complete)` then `next_work()` (which validates). Orchestrator does NOT end the builder session until `next_work` confirms gates passed and says to dispatch review.
6. **Demo promotion automation in finalize** — `telec todo demo create {slug}` as a finalize step. Promotes `todos/{slug}/demo.md` to `demos/{slug}/demo.md` and generates minimal metadata.
7. **snapshot.json reduction** — Strip acts narrative and metrics (duplicated by `delivered.yaml` and git). Reduce to `{slug, title, version}` for demo listing and semver gate, or kill entirely and add `version` to `delivered.yaml`.
8. **Daemon restart after finalize** — After the finalizer merges to main and cleanup is done, `make restart` must run before the next `next_work()` call. Without this, the daemon runs stale code and the next work item is processed with the old version. Goes in POST_COMPLETION for `next-finalize`, between cleanup and `next_work()`.
9. **Lazy state marking** — `next_work()` must not mutate state before returning dispatch instructions. Currently it marks the next item as `in_progress` and `build: started` as a side effect before the orchestrator sees the output. If the user declines to continue, the item is orphaned as started. Fix: move state marking into the output instructions so the orchestrator only executes them when actually dispatching.

### Out of scope

- Full demo execution as a build gate (structural validation only for first phase).
- Changes to `mark_phase()` — stays a dumb state writer.
- Changes to command files — commands are thin wrappers around procedures.
- New CI workflows or changes to existing `.github/workflows/`.
- Retroactive demo generation for past deliveries.
- **Procedure, spec, template, policy, and skill documentation updates** — split to `lifecycle-enforcement-docs` (depends on this todo).

## Success Criteria

- [ ] `telec todo demo validate {slug}` exits 1 on scaffold template (no blocks).
- [ ] `telec todo demo validate {slug}` exits 0 on `<!-- no-demo: reason -->` and logs reason.
- [ ] `telec todo demo validate {slug}` exits 0 on demo.md with bash blocks (structural, no execution).
- [ ] `telec todo demo run {slug}` extracts and executes bash blocks with exit-1 fix.
- [ ] `telec todo demo create {slug}` promotes demo.md to `demos/{slug}/` with minimal metadata.
- [ ] `telec todo demo` (no args) lists available demos (preserved).
- [ ] `next_work()` runs `make test` + `telec todo demo validate` after build marked complete.
- [ ] Gate failure resets build to `started`, returns message-builder instruction.
- [ ] Gate success returns end-session + dispatch-review instruction.
- [ ] POST_COMPLETION for `next-build` no longer ends session before `next_work()`.
- [ ] After finalize, `make restart` runs before next `next_work()`.
- [ ] `next_work()` does not mutate state when returning dispatch instructions for a new item.
- [ ] Declining to continue leaves the next item in `pending` state, not orphaned.
- [ ] All existing tests pass (`make test`).

## Constraints

- `mark_phase()` must not gain validation logic — state writer primitive only.
- Builder session stays alive during gate validation. Orchestrator does NOT end session before gates pass.
- `validate` is structural only (blocks exist?) — no execution. `run` executes.
- Defense in depth: builder self-validates -> state machine re-validates -> CI validates.
- Demo template must have no bash blocks so it starts as failing validation.

## Risks

- `next_work()` gate subprocess calls could hang in broken worktrees. Mitigation: subprocess timeouts.
- Builder-stays-alive loop is new orchestrator behavior. Mitigation: terminates when gates pass or orchestrator manually ends.
- snapshot.json reduction affects presenter and listing. Mitigation: narrative from source artifacts; listing from reduced snapshot or delivered.yaml.
- snapshot.json `version` is pre-release (from pyproject.toml), not actual release version (from CI semver bump). Acceptable — semver gate only needs major version.
- Cleaned-up items lose source artifacts for narrative. Mitigation: presenter falls back to demo.md walkthrough only. Old full snapshots work via backward compat.
