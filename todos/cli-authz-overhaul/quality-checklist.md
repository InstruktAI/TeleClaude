# Quality Checklist: cli-authz-overhaul

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 2928 passed
- [x] Lint passes (`make lint`) — 9.40/10, no regression (+0.00)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate cli-authz-overhaul` exits 0) — 3 executable blocks found
- [x] Working tree clean (orchestrator-managed drift files excluded)
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope — no deferrals.md, out-of-scope items documented in requirements
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — REQUEST CHANGES
- [ ] Critical issues resolved or explicitly blocked — C1: 9 commands have wrong system-role gate
- [x] Test coverage and regression risk assessed

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
