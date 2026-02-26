# Quality Checklist: skills-procedure-taxonomy-alignment

This checklist is the execution projection of the build procedure for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [ ] Requirements implemented according to scope
- [ ] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] No silent deferrals in implementation plan
- [ ] Code committed
- [ ] Demo validated (`telec todo demo validate skills-procedure-taxonomy-alignment` exits 0, or exception noted)
- [ ] Working tree clean
- [ ] Manual verification: taxonomy doc exists and names in-scope skills
- [ ] Manual verification: procedure docs exist (5 files, one per skill)
- [ ] Manual verification: wrappers have `## Required reads` pointing to procedure docs
- [ ] Manual verification: `rg -n "^## Required reads" agents/skills/*/SKILL.md` shows all 5 in-scope skills

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
