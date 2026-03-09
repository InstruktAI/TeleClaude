# mirror-runtime-isolation-2 — Input

## Bug: telec todo work (no slug) re-enters in-progress items

### Reproduction
1. `telec todo work todo-phase-status-display` completes finalize handoff
2. State machine says to continue with `telec todo work` (no slug)
3. Instead of finding the next ready item, it picks up `mirror-runtime-isolation` which is already `in_progress` with `build: complete`
4. It re-runs build gates on mirror-runtime-isolation — which fails on pre-existing test failures

### Expected behavior
`telec todo work` without a slug should either:
- Skip items already in_progress (they have their own orchestrator)
- Continue the item from its current phase (review, not re-gate build)

### Actual behavior
It re-enters the build gate phase for an item that already passed build and should be in review.

### Evidence
- `telec roadmap list` shows mirror-runtime-isolation as `[in_progress] [Build:complete]`
- The state machine returned `progress_reason: build_gates_failed_post_review` — it's running post-review gates on an item that hasn't been through review yet in this session
