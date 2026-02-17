# Quality Checklist: doc-access-control

## Build Gates (Builder)

- [ ] All implementation-plan tasks checked off
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] Working tree clean (build-scope changes committed)
- [ ] Commits exist for each task

## Review Gates (Reviewer)

- [ ] Requirements met (FR1–FR5)
- [ ] No regressions in existing audience filtering
- [ ] Access-denied notice for forbidden Phase 2 requests
- [ ] CLI gating error message is clear and actionable
- [ ] Snippet schema docs updated with clearance field

## Finalize Gates (Finalizer)

- [ ] Branch merged or PR created
- [ ] Delivery logged
- [ ] Cleanup completed
