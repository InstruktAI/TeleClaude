# Quality Checklist: slug-helper

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 2849 pass; 0 failures
- [x] Lint passes (`make lint`) — score 9.40/10; all issues pre-existing
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate slug-helper` exits 0 — 4 executable blocks found)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed — `create_todo_skeleton`, `create_bug_skeleton` no longer raise `FileExistsError`; `_derive_slug` delegates character normalization to `normalize_slug`

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — all 7 success criteria verified; 1 incomplete desync fix found
- [x] Deferrals justified and not hiding required scope — no deferrals.md present
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs) — 4 valid blocks
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — REQUEST CHANGES
- [ ] Critical issues resolved or explicitly blocked — 1 Critical: stale slug in `_handle_todo_dump` event payload
- [x] Test coverage and regression risk assessed — solid coverage, suggestions for invariant tests

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
