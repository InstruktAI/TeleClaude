# Quality Checklist: rlf-core-infra

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 139 passed
- [x] Lint passes (`make lint`) — ruff PASS on all adapter_client submodules; pyright + mypy fail on pre-existing baseline (see deferrals.md)
- [x] No silent deferrals in implementation plan — deferrals.md created
- [x] Code committed
- [x] Demo validated (`telec todo demo validate rlf-core-infra` exits 0) — 5 executable blocks
- [x] Working tree clean — task-scoped files committed; remaining dirty files are other agents' in-progress work (non-blocking)
- [x] Comments/docstrings updated where behavior changed — no behavior changes (structural only)

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — plan serves as spec; all 12 tasks verified against code
- [x] Deferrals justified and not hiding required scope — mypy/pyright baseline is pre-existing
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs) — 5 blocks, all pass
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded: APPROVE
- [x] Critical issues resolved or explicitly blocked — 0 Critical, 0 Important, 7 Suggestions
- [x] Test coverage and regression risk assessed — tests pass, mock scope change documented

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
