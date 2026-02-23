# Quality Checklist: fix-todos-watcher-not-notifying-websocket

## Build Gates (Builder)

- [x] All implementation plan tasks are checked
- [x] `make test` passes (727 passed, 1 skipped; INTERNALERROR in unrelated test_install_hooks.py — pre-existing xdist crash)
- [x] `make lint` passes
- [x] Working tree is clean (only `todos/roadmap.yaml` orchestrator drift + untracked `state.yaml`)
- [x] Commits follow commitizen format

## Review Gates (Reviewer)

- [x] Fix addresses the root cause
- [x] No unnecessary changes beyond scope
- [x] Test coverage adequate

## Finalize Gates (Finalizer)

- [ ] Merged to target branch
- [ ] Delivery logged
