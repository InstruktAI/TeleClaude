# Deferrals: identity-origin-cleanup

## Deferred Tasks

### Task 6b: Convert edge adapters from `channel_metadata` dicts to typed origin metadata (partial)

**Completed:** All `CreateSessionCommand(channel_metadata=)` calls in edge adapters (telegram
private_handlers x2, discord gateway_handlers x2, discord input_handlers x2, whatsapp_handler x1)
replaced with `origin_metadata=`. Session creation path is clean.

**Remaining scope:** Adapters still pass `channel_metadata` dicts to `MessageMetadata` for
per-message context (telegram message_id, discord actor fields). These use the deprecated
`MessageMetadata.channel_metadata` field which still exists. Converting these to typed metadata
or named fields is deferred.

**Impact of remaining deferral:** `MessageMetadata.channel_metadata` remains as a deprecated field
for per-message context. Adapters continue to function. No regression.

**Suggested outcome:** NEW_TODO
**Outcome reason:** Independent work scoped tightly for per-message metadata typing across all adapters. Can be completed once identity-origin-cleanup completes. Created as `identity-origin-cleanup-task-6b`.

### Task 7: Promote target_computer and actor context to named fields

**Scope:** Redis transport messaging, fanout coordinator, add named fields to MessageMetadata.

**Why deferred:** Requires adding 5+ named fields to MessageMetadata and updating Redis serialization.
The current code uses the deprecated `channel_metadata` dict for actor context and target_computer.
This works and can be cleaned up independently.

**Impact of deferral:** Actor context and target_computer routing continue via the deprecated
`channel_metadata` field on MessageMetadata. No regression.

**Suggested outcome:** NEW_TODO
**Outcome reason:** Independent work for Redis/fanout architecture. Focused scope with clear success criteria. Created as `identity-origin-cleanup-task-7`.

### Task 8: Refactor daemon headless session creation via command pipeline

**Scope:** `teleclaude/daemon_hook_outbox.py` — replace direct `db.create_headless_session()` with
`CreateSessionCommand` through the command service.

**Why deferred:** Independent from the channel_metadata elimination. The daemon's direct DB call
works correctly; routing through the command pipeline is an architectural improvement.

**Impact of deferral:** Daemon headless sessions continue to work via direct DB call.

**Suggested outcome:** NEW_TODO
**Outcome reason:** Architectural improvement that centralizes session creation path. Independent scope with clear implementation target. Created as `identity-origin-cleanup-task-8`.

### Task 9: Remove resolve_from_terminal and update CLI callers

**Scope:** `teleclaude/core/identity.py` + 3 CLI files.

**Why deferred:** Depends on Task 8 (daemon must stop calling resolve_from_terminal first).
CLI callers need an alternative path before the method can be removed.

**Impact of deferral:** `resolve_from_terminal()` continues to exist and work.

**Suggested outcome:** NOOP
**Outcome reason:** Blocked by Task 8 completion. Will create a new todo once Task 8 is finished and verified.

### Task 10: Verify `channel_metadata` elimination and final cleanup

**Scope:** Verification scan + documentation comment.

**Why deferred:** Cannot complete until Tasks 6b and 7 remove all `channel_metadata` usage
from MessageMetadata. The verification pass is meaningful only after full elimination.

**Impact of deferral:** None — this is a verification step.

**Suggested outcome:** NOOP
**Outcome reason:** Blocked by Tasks 6b and 7 completion. Will create a new todo once both are finished and verified.
