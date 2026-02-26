# Quality Checklist: help-desk-whatsapp

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
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Manual verification notes (Builder, February 26, 2026):

- Ran `make test` and confirmed `2197 passed, 106 skipped`.
- Ran `make lint` and confirmed completion (`ruff check`, `pyright`) with zero errors.
- Ran `telec todo demo validate help-desk-whatsapp` and confirmed `16 executable block(s)`.
- Live WhatsApp Cloud API verification remains blocked in this environment (no provisioned account/token pair and no externally reachable webhook endpoint).

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
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
