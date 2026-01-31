# Refactor Again — Implementation Plan

## Goals

- Keep hook normalization at the boundary, but move all session lifecycle mutations into core.
- Make headless sessions first-class and core-owned.
- TTS listens only to AGENT_EVENT and handles only AGENT_SESSION_START + AGENT_STOP.
- Replace stringly last_input_origin with a single enum/constant set.
- Remove "cli" origin; introduce explicit origins (api, hook, mcp, telegram, redis, etc.).
- MCP-started sessions set last_input_origin=mcp explicitly.

## Current observations

- TUI session view does not use last_input_origin, so origin changes should not break selection logic.
- Hook receiver normalizes and also mutates DB (creates headless session, writes native ids/log). This is the core leakage to remove.

## Plan

1. Define origin constants
   - Introduce InputOrigin enum/constant set in core.
   - Replace string literals for last_input_origin with InputOrigin values.
   - Remove "cli" from the allowed set and update comparisons.
   - Add explicit origins: api, hook, mcp, telegram, redis (and others already used if any).

2. MCP origin behavior
   - Update MCP session creation to set last_input_origin=InputOrigin.MCP.
   - Stop inheriting parent origin for MCP-created sessions.

3. Headless sessions first-class (core-owned)
   - Move headless session creation into core (daemon/service), not hook receiver.
   - Add a core helper (e.g., ensure_headless_session) that resolves by agent+native_session_id.
   - Move native_session_id/native_log_file updates into daemon dispatch path.

4. Hook receiver boundary-only behavior
   - Keep normalization in receiver.
   - Remove DB writes from receiver (no session creation or updates).
   - Receiver enqueues normalized payload + agent + event_type only.

5. TTS event scope
   - Ensure TTS only subscribes to TeleClaudeEvents.AGENT_EVENT.
   - Handle only AgentHookEvents.AGENT_SESSION_START and AgentHookEvents.AGENT_STOP.
   - Remove any other subscriptions or fallbacks.

6. Docs update
   - Update TTS architecture doc (already adjusted) to reflect AGENT_EVENT-only input.
   - Document InputOrigin enum and new origin semantics (api/hook/mcp) in relevant docs.
   - Document headless session behavior as core-owned.

## DoD (Definition of Done)

- No direct DB writes in hook receiver for session lifecycle or metadata.
- Headless sessions created in core; receiver only normalizes + enqueues.
- last_input_origin uses constants only; "cli" removed across code and docs.
- MCP sessions explicitly store last_input_origin=mcp.
- TTS listens only to AGENT_EVENT for AGENT_SESSION_START + AGENT_STOP.
- Docs updated for origins + headless sessions + TTS flow.
- TUI behavior unaffected (origin not used in selection logic).
