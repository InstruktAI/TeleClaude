# Quality Checklist - ucap-tui-adapter-alignment

## Build Gates (Builder)

- [x] All tasks in `implementation-plan.md` are checked `[x]`
- [x] Tests pass: `make test` — 2123 passed, 106 skipped
- [x] Lint passes: `make lint` — 0 errors, 0 warnings
- [x] Demo validates: `telec todo demo validate ucap-tui-adapter-alignment` — 2 executable blocks found
- [x] Demo artifact delivered: `demos/ucap-tui-adapter-alignment/demo.md` copied
- [x] Manual verification: no user-facing UI change (canonical types replace hook types transparently; behavior for agent_stop and tool_use is equivalent; user_prompt_submit now correctly triggers input highlight instead of being silently dropped via dead "agent_input" branch)
- [x] Working tree clean (build-scope changes committed; `todos/ucap-tui-adapter-alignment/state.yaml` orchestrator drift is non-blocking)
- [x] Commits exist: `git log --oneline -5` shows build commits

## Review Gates (Reviewer)

_Populated by reviewer._

## Finalize Gates (Finalizer)

_Populated by finalizer._
