# Quality Checklist: atomic-layout-messages

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 4221 passed, 0 failed, 8 xfailed
- [x] Lint passes (`make lint`) — ruff, pyright, mypy, pylint all clean on changed files
- [x] No silent deferrals in implementation plan
- [x] Code committed — 12 commits on branch
- [x] Demo validated (`telec todo demo validate atomic-layout-messages` exits 0, 3 executable blocks)
- [x] User-facing verification evidence recorded — TUI message bus change; verified via unit tests exercising all 3 dual-change call sites (Space double-press, double-click, batch-toggle-off) and bridge/app handlers. No browser UI — this is internal Textual message plumbing.
- N/A Browser-based frontend or web UI changes smoke-tested with Playwright — change is internal message bus, no browser rendering
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES)
- [x] Critical issues resolved or explicitly blocked
- [x] Test coverage and regression risk assessed
- [x] User-facing verification evidence reviewed
- [x] Browser-based frontend or web UI changes verified with Playwright during review, or gap recorded as a finding

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
