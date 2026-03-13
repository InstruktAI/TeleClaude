# Quality Checklist: rlf-core-data

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 139 passing
- [x] Lint passes (`make lint`) — ruff ✓, pyright ✓, mypy ✓; guardrail fails on 18 pre-existing modules outside scope (see deferrals.md). Was already failing before this task (21 violations).
- [x] No silent deferrals in implementation plan — documented in deferrals.md
- [x] Code committed — 3 commits: Phase 1 (models), Phase 2 (command_handlers), Phase 3 (db)
- [x] Demo validated (`telec todo demo validate rlf-core-data`) — 6 executable blocks
- [x] Working tree clean (task-scope files only; unrelated ruff formatting drift non-blocking per policy)
- [x] Comments/docstrings updated where behavior changed — structural only, no behavior changes

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
