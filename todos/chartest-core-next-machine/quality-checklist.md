# Quality Checklist: chartest-core-next-machine

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`)
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate chartest-core-next-machine` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Build notes:

- Added 14 characterization test files under `tests/unit/core/next_machine/`, one for each mapped source file in the todo scope.
- Manual verification: ran the full targeted next-machine characterization suite and confirmed the new tests pass without production code changes.
- Resolved a repo-level build-gate blocker in `teleclaude/events/envelope.py` so the existing sandbox event tests instantiate `EventEnvelope` correctly under the current Pydantic version.
- Working tree note: the only remaining dirty file during build was the orchestrator-managed `todos/chartest-core-next-machine/state.yaml`, which was left untouched per policy.

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES)
- [x] Critical issues resolved or explicitly blocked
- [x] Test coverage and regression risk assessed

Review notes:

- Verdict: APPROVE.
- Auto-remediated 4 string assertions on human-facing text across 3 test files.
- No deferrals found. No critical findings.
- Demo validated: both bash blocks exercise real delivered behavior.
- R1-F1 resolved by `cd6712c3b`; R1-F2 resolved by `88ec7455a`; applied-fix documentation recorded in `9213e3a87`.

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
