# Quality Checklist: chartest-core-db

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
- [x] Demo validated (`telec todo demo validate chartest-core-db` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

### Build Notes

- Manual verification: `pytest tests/unit/core/db -q -n0` passed with `51 passed in 2.70s`, covering every new source-mapped characterization file under `tests/unit/core/db/`.
- Manual verification: `pytest tests/unit/events/sandbox/test_bridge.py tests/unit/events/sandbox/test_runner.py -q -n0` passed with `19 passed`, confirming the sandbox-event baseline fix for `EventEnvelope`.
- Gate result: `make test` passed with `216 passed, 1 warning`.
- Gate result: `make lint` passed.
- Gate result: `telec todo demo validate chartest-core-db` passed and accepted the `no-demo` marker for this internal test-only delivery.
- Working tree status after task-scoped commits is clean apart from orchestrator-managed drift in `todos/chartest-core-db/state.yaml`.
- Production behavior did not change; no comment or docstring updates were required in source files.
- Resumed build verification: `make test` passed with `811 passed, 4 warnings` after aligning `tests/unit/core/db/test__base.py` to the current `DbBase._serialize_session_metadata()` behavior, which serializes all `SessionMetadata` fields via `dataclasses.asdict()`, including null-valued identity keys.
- Resumed build verification: `make lint` passed without repo-wide failures after the characterization assertion fix.

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES)
- [x] Critical issues resolved or explicitly blocked
- [x] Test coverage and regression risk assessed

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
