# Quality Checklist: tdd-enforcement-single-test-contract

This checklist projects Definition-of-Done for strict TDD contract enforcement.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [ ] `test-contract.md` exists and is approved/locked before build starts
- [ ] Builder/fixer lanes changed code only (no locked test file edits)
- [ ] `next_work` precondition checks enforce contract lock state
- [ ] Contract hash/state handling implemented deterministically
- [ ] Tests for guard behavior pass
- [ ] Lint passes (`make lint`)
- [ ] Code committed
- [ ] Working tree clean (excluding approved orchestrator drift)

## Review Gates (Reviewer)

- [ ] Requirements map to explicit contract test cases
- [ ] Contract integrity checks are present in workflow
- [ ] Role-scoped immutability guard blocks forbidden test edits
- [ ] Transitional mode (if any) is explicit, logged, and constrained
- [ ] Findings documented in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build and Review gates all checked
- [ ] Policy/docs/templates/runtime are aligned
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap and cleanup steps complete
