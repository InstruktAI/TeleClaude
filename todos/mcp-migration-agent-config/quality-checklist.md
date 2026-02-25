# Quality Checklist: mcp-migration-agent-config

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
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Build verification notes (2026-02-25):

- `make test` passed (2186 passed, 106 skipped).
- `make lint` passed.
- `telec todo demo validate mcp-migration-agent-config` passed.
- Semi-automated session/role validation completed via focused tests for:
  MCP-disabled flags, worker 403 enforcement, tmux identity mismatch handling,
  context visibility filtering, job execution path, and per-session TMPDIR marker behavior.

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
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
