# Help Desk Discord — Quality Checklist

## Build Gates (Builder)

- [x] All implementation-plan tasks checked off
- [x] Tests pass (`make test`) — 808 passed, 2 pre-existing failures (bootstrap signature, agent resume profile)
- [x] Lint passes (`make lint`)
- [x] Working tree clean (build-scope changes committed) — only orchestrator drift in todos/roadmap.md and todos/dependencies.json
- [x] Commits verified (`git log --oneline -10`) — 8 commits for 8 tasks

## Review Gates (Reviewer)

- [ ] Code matches requirements
- [ ] Tests cover behavioral contracts
- [ ] No regressions in existing tests
- [ ] Commit messages follow commitizen format

## Finalize Gates (Finalizer)

- [ ] Branch merged or PR created
- [ ] Delivery metadata recorded
- [ ] Cleanup completed
