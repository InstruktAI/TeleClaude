# Quality Checklist: rlf-services

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 139/139
- [x] Lint passes (`make lint`) — DEFERRED: 19 pre-existing oversized files outside scope fail guardrails; our target files (api_server.py, daemon.py) are both under 1000 lines; ruff/pyright/mypy pass on all new/changed files; see deferrals.md
- [x] No silent deferrals in implementation plan — deferrals.md created
- [x] Code committed
- [x] Demo validated (`telec todo demo validate rlf-services` exits 0) — 4 executable blocks found
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

**Manual verification:**
- `wc -l teleclaude/api_server.py teleclaude/daemon.py` confirms 906 and 859 lines respectively
- `python3 -c "from teleclaude.daemon import TeleClaudeDaemon; print('ok')"` passes
- `python3 -c "from teleclaude.api import sessions_routes, sessions_actions_routes; print('ok')"` passes
- All 139 tests pass with no regressions

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
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
