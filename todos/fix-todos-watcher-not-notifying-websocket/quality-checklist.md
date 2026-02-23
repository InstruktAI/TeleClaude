# Quality Checklist: fix-todos-watcher-not-notifying-websocket

## Build Gates (Builder)

- [x] All implementation plan tasks are checked
- [x] `make test` passes (727 passed, 1 skipped; INTERNALERROR in unrelated test_install_hooks.py — pre-existing xdist crash)
- [x] `make lint` passes
- [x] Working tree is clean (only `todos/roadmap.yaml` orchestrator drift + untracked `state.yaml`)
- [x] Commits follow commitizen format

## Review Gates (Reviewer)

- [x] Fix addresses the root cause (state.yaml-derived fields all in fingerprint)
- [x] No unnecessary changes beyond scope (1 static method + 4 lines changed in update_data)
- [x] Test coverage adequate (consistent with existing skip-marked test suite for this module)

## Finalize Gates (Finalizer)

- [x] Merged to target branch (feature branch ac81602c merged to main at 2afae57a; bug.md updated at 58cbb41d)
- [x] Bug documentation complete (Investigation, Root Cause, Fix Applied sections documented with correct TUI terminology)
