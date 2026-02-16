# Help Desk Discord — Quality Checklist

## Build Gates (Builder)

- [ ] All implementation-plan tasks checked off
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] Working tree clean (build-scope changes committed)
- [ ] Commits verified (`git log --oneline -10`)

## Review Gates (Reviewer)

- [ ] Code matches requirements
- [ ] Tests cover behavioral contracts
- [ ] No regressions in existing tests
- [ ] Commit messages follow commitizen format

## Finalize Gates (Finalizer)

- [ ] Branch merged or PR created
- [ ] Delivery metadata recorded
- [ ] Cleanup completed
