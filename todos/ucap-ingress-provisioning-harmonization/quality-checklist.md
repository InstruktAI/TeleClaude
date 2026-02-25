# Quality Checklist: ucap-ingress-provisioning-harmonization

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 186 passed
- [x] Lint passes (`make lint`) — via pre-commit hook on each commit
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate ucap-ingress-provisioning-harmonization` exits 0, or exception noted) — 4 executable blocks found
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed — no behavior changed; audit confirmed existing code correct

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — R1–R4 audit claims verified against source; R5 observability gap identified
- [x] Deferrals justified and not hiding required scope — no deferrals.md exists; no silent deferrals found
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — REQUEST CHANGES
- [x] Critical issues resolved or explicitly blocked — no critical issues
- [x] Test coverage and regression risk assessed — R5 logging invariant has zero regression coverage; `/tmp` paths not parallel-safe

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
