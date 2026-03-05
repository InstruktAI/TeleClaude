# Quality Checklist: event-system-cartridges

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test` — 2762 pass; 1 pre-existing flaky test in test_next_machine_hitl unrelated to this slug)
- [x] Lint passes (`make lint` — 9.40/10, unchanged from baseline; all pre-existing issues)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate event-system-cartridges` exits 0, 5 executable blocks)
- [x] Working tree clean (orchestrator-managed drift in roadmap.yaml and state.yaml excluded)
- [x] Comments/docstrings updated where behavior changed (NotificationProjectorCartridge fast-path documented inline)

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope (no deferrals.md exists)
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE — round 2: 1 Important non-blocking, 5 Suggestions)
- [x] Critical issues resolved or explicitly blocked (no Critical findings; round 1 Important findings both resolved)
- [x] Test coverage and regression risk assessed

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
