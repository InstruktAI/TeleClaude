# Requirements: adapter-reflection-cleanup

## Goal

Close the gap between the reflection pipeline architecture (documented) and its
implementation (current code). Core becomes a dumb broadcast pipe that sends raw
text + metadata to every adapter. Adapters own all presentation, suppression, and
local routing decisions.

## Scope

### In scope

- Remove `_fanout_excluding` from reflection broadcast path — core sends to ALL adapters
- Remove all presentation logic from `broadcast_user_input` (headers, formatting,
  adapter-type checks)
- Add `reflection_origin: str | None` to `MessageMetadata`
- Replace private adapter reach-ins with public base-class methods
- Implement adapter-local reflection handling in Telegram and Discord
- Parallelize `deliver_inbound` per architecture flow §4
- Update/move tests to match new ownership boundaries

### Out of scope

- Echo guard overhaul (timing heuristic is working, improvement deferred)
- Changes to the two broadcast paths (intentional architecture)
- WhatsApp adapter (not yet implemented)
- Changes to non-reflection broadcast paths (output stream, notices, etc.)

## Success Criteria

- [ ] `broadcast_user_input` contains zero presentation logic — no header construction,
      no `render_reflection_text`, no `adapter.ADAPTER_KEY` checks, no `display_origin_label`
- [ ] `broadcast_user_input` sends to ALL adapters including source — no `exclude` parameter
- [ ] `MessageMetadata.reflection_origin` field exists and is populated on every reflection
- [ ] Telegram adapter: suppresses own-user reflections, renders others with attribution
      to admin topic (header + separator)
- [ ] Discord adapter: suppresses own-user reflections, renders others via existing
      webhook path with attribution
- [ ] `break_threaded_turn` uses public `drop_pending_output()` — no `_qos_scheduler` access
- [ ] `move_badge_to_bottom` calls public method on base class
- [ ] `deliver_inbound` runs tmux inject, broadcast, and break_threaded_turn in parallel
      (DB update stays before broadcast for echo guard dependency)
- [ ] All existing tests pass; reflection formatting tests live at adapter level
- [ ] `_fanout_excluding` is either removed entirely or no longer used in reflection paths

## Constraints

- Feature flag system (`feature_flags.py`, `experiments.yml`) must be preserved
- `_broadcast_to_ui_adapters` serialization stays (documented adapter_metadata blob
  clobbering concern) — only reflection fanout changes
- Echo guard (`is_recent_routed_echo`) must continue working through the refactor
- DB update in `deliver_inbound` must precede broadcast (echo guard reads persisted state)

## Dependencies

- None — all required architecture docs already exist

## Risks

- Removing `_fanout_excluding` without adapter-local suppression causes own-user echo.
  Mitigation: implement adapter suppression in the same phase as the core change.
- Parallelizing `deliver_inbound` could surface latent race conditions.
  Mitigation: DB update stays sequential before the parallel gather.
