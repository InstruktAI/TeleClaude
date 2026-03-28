# Quality Checklist: os-managed-todo-watchers

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
- [x] Demo validated (`telec todo demo validate os-managed-todo-watchers` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Build notes:

- Verified `uv run telec init -h` advertises docs sync and todo watcher service installation.
- `telec todo demo validate os-managed-todo-watchers` passed with executable demo blocks present.
- `make test` passed after restoring the explicit-timeout guard in `tests/conftest.py`.
- `make lint` passed, including the updated lifecycle doc references and watcher-facing help text.

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
