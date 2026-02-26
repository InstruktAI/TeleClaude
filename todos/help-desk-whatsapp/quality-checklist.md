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

Build verification notes (2026-02-26):

- `make test` passed (`2197 passed, 106 skipped`).
- `make lint` passed (ruff/pyright clean; existing resource warnings remain non-blocking in repository baseline).
- `telec todo demo validate help-desk-whatsapp` passed (`16 executable block(s) found`).
- Demo artifact was synchronized from `todos/help-desk-whatsapp/demo.md` to `demos/help-desk-whatsapp/demo.md`.
- Live WhatsApp Cloud API/manual callback verification is not possible in this environment (no externally reachable webhook endpoint or provisioned production credentials).

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
