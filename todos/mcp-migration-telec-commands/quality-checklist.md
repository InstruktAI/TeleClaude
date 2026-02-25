# Quality Checklist: mcp-migration-telec-commands

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 1805 passed, 3 pre-existing failures unrelated to this slug
- [x] Lint passes (`make lint`) — 0 errors, 0 warnings
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

**Manual verification:**

- `telec sessions -h` shows 11 subcommands with rich help ✓
- `telec agents -h` shows availability + status subcommands ✓
- `telec channels -h` shows list + publish subcommands ✓
- `telec todo demo validate mcp-migration-telec-commands` passes: 6 executable blocks ✓
- Legacy aliases (list/claude/gemini/codex) removed from TelecCommand enum ✓
- `telec --help` no longer shows list/claude/gemini/codex ✓

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
