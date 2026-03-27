# Plan Review Findings: identity-origin-cleanup

## Resolved During Review

### PRF-1 (Important — resolved): Task ordering creates transient behavioral regression

Tasks 4 → 5 → 6 order breaks `initiator_session_id` flow for API-originated sessions.
Currently `initiator_session_id` flows: route injects into `channel_metadata` →
handler reads from fallback. Removing the handler fallback (Task 4) before the routes
(Task 6) and mapper (Task 5) pass it through first-class fields creates a window where
`initiator_session_id` is lost.

**Resolution:** Added sequencing constraint to Task Order section: Tasks must be applied
in order 6 → 5 → 4 (routes first, mapper second, handler last).

### PRF-2 (Important — resolved): Task 6 email handling ambiguous for non-initiator sessions

Task 6 said both "stop injecting email into channel_metadata" and "edge metadata for
direct sessions" — contradictory on their face. The builder needs to know what replaces
the injection for sessions without an initiator.

**Resolution:** Clarified in Task 6: for non-initiator sessions, construct typed origin
metadata (`WebOriginMetadata(email=...)` or `TerminalOriginMetadata(email=...)`) and pass
as `channel_metadata`. The Mapping protocol from Task 1 makes the resolver work unchanged.

## Suggestions (unresolved — non-blocking)

### PRF-3: Task 8 references non-existent API

Task 8 says `get_command_service().execute()` but the actual API is
`get_command_service().create_session(cmd)`. Minor naming error; the builder would
discover the correct method from the codebase.

### PRF-4: Second `db.create_headless_session()` caller unaddressed

The revive endpoint in `sessions_actions_routes.py:148` also calls
`db.create_headless_session()`. This prevents full removal of the method per R6 success
criteria ("removed or deprecated after all callers are migrated"). The revive endpoint
is out of scope for R6 (not daemon headless), but the plan should acknowledge the method
cannot be fully removed yet.

### PRF-5: Task 7 target_computer wiring underspecified

Task 7 says "route `parsed.initiator` through the existing
`RedisTransportMetadata.target_computer` field" but doesn't detail how `target_computer`
gets from the Redis message handler to `forward_command`. The builder would need to trace
the wiring path independently.
