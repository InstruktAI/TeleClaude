# Quality Checklist: web-tui-shell

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]` (plan uses task headers, not checkboxes — all 11 tasks committed)
- [x] Tests pass (`make test`) — 171 tests, 16 files, all green
- [x] Lint passes (`make lint`) — pre-existing pylint C0103 on Python migration module; all TS code clean
- [x] No silent deferrals in implementation plan
- [x] Code committed — 11 atomic commits (T1-T11)
- [x] Demo validated (`telec todo demo validate web-tui-shell` exits 0)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed
- [x] Design token audit: `grep -r '#[0-9a-fA-F]' frontend/components/tui/ frontend/components/sidebar/NewSessionDialog.tsx` returns nothing
- [x] Demo artifact copied to `demos/web-tui-shell/demo.md`

**Manual verification note:** Build environment is a worktree — no dev server available for visual inspection. All component behavior verified through unit and integration tests with happy-dom.

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — all components wired into page.tsx
- [x] Deferrals justified and not hiding required scope — no deferrals.md present
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs) — demo matches wired behavior
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — **APPROVE**
- [x] Critical issues resolved or explicitly blocked — all 3 Critical and 8 Important resolved
- [x] Test coverage and regression risk assessed — 180/180 tests pass, including ChatPage integration

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
