# Quality Checklist: job-report-notifications

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 1815 pass, 44 pre-existing TUI failures unrelated to this branch
- [x] Lint passes (`make lint`) — 0 pyright errors, ruff clean
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Working tree clean (only `todos/job-report-notifications/state.json` dirty — orchestrator-synced)
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — all 15 success criteria mapped to code
- [x] Deferrals justified and not hiding required scope — no deferrals exist
- [x] Findings written in `review-findings.md` — 0 critical, 2 important, 3 suggestions
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — APPROVE
- [x] Critical issues resolved or explicitly blocked — no critical issues found
- [x] Test coverage and regression risk assessed — comprehensive coverage, migration script gap noted

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
