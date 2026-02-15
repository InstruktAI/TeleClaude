# Review Findings: help-desk-platform

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-15
**Verdict:** REQUEST CHANGES

---

## Critical

### C1: Three new MCP tools are dead code — unreachable at runtime

**Files:** `teleclaude/mcp_server.py`, `teleclaude/mcp/tool_definitions.py`, `teleclaude/mcp/handlers.py`

The implementation adds handler methods for `teleclaude__publish`, `teleclaude__channels_list`, and `teleclaude__escalate` in `handlers.py`, but none of them are wirable:

- `teleclaude__escalate`: Missing from `ToolName` enum in `mcp_server.py` AND missing from `tool_definitions.py`. No definition, no enum, no dispatch.
- `teleclaude__publish` and `teleclaude__channels_list`: Present in `ToolName` enum and `tool_definitions.py`, but have NO entries in the `tool_handlers` dispatch dict (`mcp_server.py` lines 571-592).

All three tools are unreachable. Calling them returns an unhandled-tool error. This blocks success criteria SC-05 (escalation), SC-06 (channels), and SC-07 (publish).

**Evidence:** `grep -r "teleclaude__escalate" teleclaude/mcp/tool_definitions.py` → no match. `grep "ESCALATE" teleclaude/mcp_server.py` → no match. `grep "PUBLISH\|CHANNELS_LIST" teleclaude/mcp_server.py` in `tool_handlers` dict → no match.

### C2: `identity_key` column missing from `schema.sql` — fresh installs fail

**File:** `teleclaude/core/schema.sql`

The `memory_observations` table definition in `schema.sql` does not include the `identity_key` column. Migration 012 adds it for existing databases, but fresh installs create the table from `schema.sql` directly. Any attempt to save an identity-scoped observation on a fresh install will raise a SQL error.

This blocks SC-01 (identity-scoped memory).

### C3: Zero new tests for ~1920 lines of new code

**Files:** All new modules; `tests/`

The implementation adds approximately 1920 lines of new production code across 58 files. The only test change is a 4-line fix in `tests/unit/test_threaded_output.py` to add `escalation_channel_id=None` to a constructor call.

No tests exist for:

- Identity key derivation and scoping (`identity.py`)
- Escalation handler logic (`handlers.py`)
- Relay routing (`discord_adapter.py` relay methods)
- Customer role tool filtering (`role_tools.py`)
- Audience-filtered context selection (`context_selector.py`)
- Channel publish/consume/worker pipeline (`channels/`)
- Bootstrap setup (`help_desk_bootstrap.py`)
- Idle compaction logic (`maintenance_service.py`)

The implementation plan explicitly called for tests on identity resolution, memory scoping, role tools, audience filtering, escalation, and relay logic. None were delivered.

---

## Important

### I1: Member audience filtering is a no-op

**File:** `teleclaude/context_selector.py`

Customer audience filtering is implemented (restricts to "public"/"help-desk" snippets), but member/operator audience filtering is only present as a comment. Members see the full unfiltered snippet set, which may expose internal-only documentation to operators who should only see "member"-tagged content.

### I2: Raw Discord content injected into tmux without sanitization

**File:** `teleclaude/adapters/discord_adapter.py` — `_handle_agent_handback`, `_compile_relay_context`

Relay messages collected from Discord are injected into the AI tmux session via `send_keys_existing_tmux` without any sanitization. A malicious or accidental message containing tmux escape sequences or shell metacharacters could interfere with the session.

### I3: Customer role does not exclude channel tools

**File:** `teleclaude/mcp/role_tools.py`

`CUSTOMER_EXCLUDED_TOOLS` removes admin tools and adds back `teleclaude__escalate`, but does not exclude `teleclaude__publish` or `teleclaude__channels_list`. Customers would be able to publish to internal channels and list channel metadata if these tools were wired (currently blocked by C1).

### I4: Relay methods lack error handling — customer messages silently lost

**File:** `teleclaude/adapters/discord_adapter.py`

`_forward_to_relay_thread`, `_handle_agent_handback`, and `_deliver_to_customer` have minimal or no error handling. If Discord API calls fail (rate limits, network errors, deleted channels), customer messages are silently dropped with no retry or notification.

### I5: Bootstrap git commands can leave partial state

**File:** `teleclaude/project_setup/help_desk_bootstrap.py`

The bootstrap sequence runs multiple git operations (init, add remote, fetch, checkout) without cleanup on failure. If any step fails mid-sequence, the directory is left in an inconsistent git state with no recovery path.

### I6: Escalation partial state risk

**File:** `teleclaude/mcp/handlers.py` — `teleclaude__escalate` handler

After creating the Discord escalation thread, `db.update_session` to set relay state is outside the try/except block. If the DB update fails, a Discord thread exists but the session has no relay state — orphaned thread with no way to route messages back.

### I7: Identity key derivation passes raw string instead of deserialized object

**File:** `jobs/session_memory_extraction.py` — `_resolve_identity_key`

The method passes `session.adapter_metadata` (a raw JSON string) to `derive_identity_key`, which expects a `SessionAdapterMetadata` object. This will fail at runtime when the extraction job runs.

### I8: Index YAML paths hardcoded to worktree

**Files:** `docs/project/index.yaml`, `docs/third-party/index.yaml`

Snippet paths are hardcoded to `~/Workspace/InstruktAI/TeleClaude/trees/help-desk-platform` instead of using relative paths or the main project path. These will break when the worktree is merged or when other developers use different paths.

### I9: Channel consumer poison pill — unacknowledged messages

**File:** `teleclaude/channels/consumer.py`

Messages that lack a `payload` field are logged but never acknowledged (no `XACK`). These messages will be re-delivered on every consumer restart, creating an ever-growing backlog of unprocessable messages.

### I10: Unsynchronized module global in channel API routes

**File:** `teleclaude/channels/api_routes.py`

The module-level `_redis` variable is set at import time or via a setup function with no thread safety. Concurrent requests could see stale or None references.

---

## Suggestions

### S1: Duplicated `_row_to_observation` helper

`db.py` and `hooks/receiver.py` both contain row-to-observation mapping logic. Consider extracting a shared helper to prevent divergence.

### S2: Job skeletons should be clearly marked or excluded

`session_memory_extraction.py` and `help_desk_intelligence.py` are stub implementations with TODO placeholders. If intentionally deferred, they should be documented in a deferrals file. If not deferred, they represent incomplete work.

### S3: `@agent` substring match may be too broad

`_is_agent_tag` in `discord_adapter.py` uses substring matching which could false-positive on messages containing "@agent" in regular conversation.

### S4: Private attribute access in identity derivation

`identity.py` accesses `ui._discord` and `ui._telegram` private attributes. Consider exposing these through the public interface.

### S5: Subscription worker dispatch targets are stubs

`channels/worker.py` subscription dispatch methods only log — no actual message processing. If intentionally deferred, document it.

### S6: `_check_idle_compaction` has no per-session error handling

**File:** `teleclaude/services/maintenance_service.py`

If one session fails during idle compaction, the exception propagates and blocks remaining sessions from being checked.

---

## Summary

| Severity   | Count |
| ---------- | ----- |
| Critical   | 3     |
| Important  | 10    |
| Suggestion | 6     |

The implementation delivers a substantial architectural foundation (identity model, relay, channels, escalation, audience filtering, bootstrap, templates) but has critical wiring gaps that make the three new MCP tools unreachable, a schema gap that breaks fresh installs, and zero test coverage for ~1920 lines of new code. Multiple error handling gaps create silent failure paths in the relay and channel subsystems.

---

## Fixes Applied

| Issue | Fix                                                                                                                                                                         | Commit     |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| C1    | Added ESCALATE to ToolName enum, escalate tool definition, and dispatch entries for all three tools (publish, channels_list, escalate)                                      | `2de02bfa` |
| C2    | Added `identity_key TEXT` column and index to `memory_observations` in schema.sql                                                                                           | `e4a7e338` |
| C3    | Added 23 unit tests covering identity key derivation, customer role filtering, audience filtering, channel consumer, bootstrap cleanup, relay sanitization, API route guard | `49fe68e3` |
| I1    | Implemented member/contributor/newcomer audience filtering (restricts to admin+member+help-desk+public)                                                                     | `bbc2762f` |
| I2    | Added `_sanitize_relay_text` to strip ANSI escapes and control characters before tmux injection                                                                             | `bbc2762f` |
| I3    | Added `teleclaude__publish` and `teleclaude__channels_list` to `CUSTOMER_EXCLUDED_TOOLS`                                                                                    | `bbc2762f` |
| I4    | Wrapped `_forward_to_relay_thread` in try/except for best-effort relay forwarding                                                                                           | `bbc2762f` |
| I5    | Bootstrap now removes partial directory via `shutil.rmtree` on git failure                                                                                                  | `bbc2762f` |
| I6    | Moved `db.update_session` inside the escalation try/except to prevent orphaned threads                                                                                      | `bbc2762f` |
| I7    | Added `SessionAdapterMetadata.from_json()` deserialization before calling `derive_identity_key`                                                                             | `bbc2762f` |
| I8    | Skipped — index.yaml paths managed by `.gitattributes` `teleclaude-docs` filter; portable after merge                                                                       | `bbc2762f` |
| I9    | Payloadless messages now acknowledged with `XACK` to prevent redelivery loop                                                                                                | `bbc2762f` |
| I10   | Added duplicate-setup guard (`RuntimeError`) to `set_redis_transport()`                                                                                                     | `bbc2762f` |
