# Output Origin Routing — Quality Checklist

## Build Gates (Builder)

- [x] All implementation-plan tasks completed
- [x] Docstring updated to reflect origin-routed delivery
- [x] Dead broadcast logging removed (replaced by `_route_to_ui` internal logging)
- [x] `make_task` factory removed (delegated to `_route_to_ui`)
- [x] Unit tests pass (`tests/unit/test_adapter_client.py` — 29/29)
- [x] Lint passes (`make lint`)
- [x] Type check passes (pyright 0 errors)
- [x] No new files created; single file modified

## Review Gates (Reviewer)

- [x] Behavioral change correct: origin-present sessions route to origin only
- [x] Fallback correct: originless sessions still broadcast to all UI adapters
- [x] No observer broadcast for output updates
- [x] Existing tests cover recovery (missing thread, topic deleted, missing metadata)
- [x] No regressions in other routing methods

## Finalize Gates (Finalizer)

- [ ] Merge to main
- [ ] Delivery logged
