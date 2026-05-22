# Quality Checklist: {slug}

This checklist is the execution projection of `definition-of-done.md` for this todo.

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
- [ ] User-facing verification evidence recorded
- [ ] Browser-based frontend or web UI changes smoke-tested with Playwright
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

### Scope & completeness

- [ ] All implementation-plan tasks checked (`[x]`); unchecked = REQUEST CHANGES
- [ ] Deferrals justified and not hiding required scope
- [ ] Requirements traced to implemented behavior — no gold-plating, no gaps

### Review lanes executed

**Read `§ Run review lanes` in `software-development/procedure/lifecycle/work/review` before executing. Each lane below must produce a section in `review-findings.md` — even "No findings." A missing section means the review is incomplete.**

- [ ] **scope**
- [ ] **code**
- [ ] **paradigm**
- [ ] **principles**
- [ ] **security**
- [ ] **tests**
- [ ] **errors**
- [ ] **types** (when types added/modified)
- [ ] **comments**
- [ ] **logging**
- [ ] **docs** (when CLI, config, or API changed)
- [ ] **simplify** (after other lanes pass)

### Quality gates

- [ ] Zero-finding justification included if 0 Important+ findings (paradigm evidence, requirement validation, copy-paste check, security evidence)
- [ ] User-facing verification evidence reviewed (or gap recorded as finding)
- [ ] Browser-based frontend or web UI changes verified with Playwright during review (or gap recorded as finding)
- [ ] Test specs: no assertions weakened or deleted vs. spec delivery commit
- [ ] Auto-remediation stays within boundaries (no scope changes, no new arch decisions, no missing-test patches)

### Verdict

- [ ] Findings written in `review-findings.md` with structured severity sections
- [ ] Verdict is arithmetic: unresolved Critical or Important > 0 → REQUEST CHANGES; both 0 → APPROVE
- [ ] Verdict stamped via `telec todo stamp {slug} --verdict approve|changes_requested --phase build_review`
- [ ] Summary and verdict reported to caller

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in todo list (status: delivered)
- [ ] Worktree cleanup complete
