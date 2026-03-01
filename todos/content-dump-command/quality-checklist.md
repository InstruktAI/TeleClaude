# Quality Checklist: content-dump-command

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
- [x] Demo validated (`telec todo demo validate content-dump-command` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

**Manual verification:** `telec content dump "Test content for build verification"` creates `publications/inbox/YYYYMMDD-test-content-for-build/` with `content.md` and `meta.yaml`. Confirmed via `tests/unit/test_content_scaffold.py` covering folder creation, slug generation, collision handling, meta fields, and CLI arg parsing (2546 passed, 106 skipped).

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
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
