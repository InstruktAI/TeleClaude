# Quality Checklist: pylint-cleanup-1

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate pylint-cleanup-1` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Build notes:

- Scoped verification passed for this todo: `pylint teleclaude/core/next_machine` and 78 focused unit tests covering touched `next_machine`, `operations`, and roadmap compatibility paths.
- `make test` still fails outside this todo because of unrelated existing repository failures in `todo_from_main`, git-wrapper permission tests, and other non-`next_machine` areas.
- `make lint` still fails outside this todo because repository-wide guardrails flag unrelated existing session-env-var usage in `daemon_session.py`, `cli/session_auth.py`, `core/integration/state_machine.py`, and `scripts/helpers/nano_banana_helper.py`.
- Demo work was skipped per orchestrator override for this lint-only cleanup.

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked
- [ ] Test coverage and regression risk assessed

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
