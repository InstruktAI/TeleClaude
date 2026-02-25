# Quality Checklist: consolidate-methodology-skills

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`) — blocked by 3 pre-existing failing tests after two retries
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo is runnable and verified
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed
- Manual verification:
  Executed `telec todo demo consolidate-methodology-skills` (3/3 executable blocks passed),
  confirmed `telec sync --validate-only` exited 0 inside demo run, and verified all six skills
  in `~/.claude/skills`, `~/.codex/skills`, and `~/.gemini/skills`.

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
