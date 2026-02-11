# Requirements: Agent Activity Events

## Goal

Replace the DB-mediated session update path with a direct, typed agent activity event pipeline. One event vocabulary flows from hook receiver to TUI/Web consumers. The database persists state for cold start; it does not drive real-time UI behavior.

## Context

Current architecture tangles persistence and real-time signaling. When a tool finishes, the coordinator writes to the DB, the DB infers a reason string from which columns changed, emits a session_updated event, the API server re-reads the session, pushes a full DTO through cache to the websocket, and the TUI parses the reason string to decide what to highlight. Four hops through persistent storage for an ephemeral signal.

The internal event vocabulary is also split: `AgentHookEventType` constants enter the system, but consumers receive `SessionUpdateReason` strings (`"agent_output"`, `"agent_stopped"`) — a separate type system that doesn't match. `_infer_update_reasons()` bridges them by reverse-engineering events from DB column changes.

This todo unifies both: one typed event flows from coordinator to consumers, and the DB is just persistence.

## Scope

In scope:

- New `AgentActivityEvent` dataclass on the existing event bus, carrying `AgentHookEventType` constants
- Coordinator emits activity events directly after processing hook events
- API server subscribes to activity events, pushes lightweight DTOs to websocket (no cache, no session re-read)
- TUI consumes typed activity events for highlight/animation logic instead of parsing reason strings from session records
- `tool_use` becomes visible in TUI: shows "Using [tool_name]..." instead of being silent
- Rename hook event types: `after_model` → `tool_use`, `agent_output` → `tool_done`
- Update external hook maps: drop unused Claude/Gemini events, add Gemini `BeforeTool` → `tool_use`
- DB column rename: `last_after_model_at` → `last_tool_use_at`, `last_agent_output_at` → `last_tool_done_at`
- Delete `SessionUpdateReason` type, `_infer_update_reasons()`, `reasons` parameter on `db.update_session()`
- DB writes become persistence-only side effects (cursor, digest, status) — no event emission for activity
- `session_updated` websocket events remain for state-change notifications (title, status, project) without reasons
- Update all architecture docs, event specs, hook docs

Out of scope:

- Web frontend implementation (consumes same activity events later)
- SSE translation adapter for AI SDK streaming
- Backpressure/queue infrastructure (not needed — event bus handles fan-out, websocket handles transport)
- OutputDistributor / stream gateway abstractions (the event bus IS the distributor)
- Replacing adapter_client message delivery (Telegram path stays unchanged)
- Input origin gating (separate concern)

## Acceptance criteria

- [ ] Zero references to `SessionUpdateReason` type in codebase
- [ ] Zero references to `_infer_update_reasons` in codebase
- [ ] Zero references to `after_model` / `AFTER_MODEL` / `agent_output` / `AGENT_OUTPUT` outside migration files and `render_agent_output` (function name kept — describes action, not event)
- [ ] `tool_use` and `tool_done` are the canonical internal event names in `AgentHookEventType` and `AgentHookEvents`
- [ ] Claude Code maps: `PreToolUse` → `tool_use`, `PostToolUse` → `tool_done`; dropped: `SubagentStart`, `SubagentStop`, `PostToolUseFailure`, `PermissionRequest`
- [ ] Gemini maps: `BeforeTool` → `tool_use`, `AfterTool` → `tool_done`; dropped: `AfterModel`, `BeforeModel`, `BeforeToolSelection`
- [ ] TUI shows "Using [tool_name]..." on `tool_use` events
- [ ] TUI shows "thinking..." on `tool_done` events (3-second timer)
- [ ] TUI shows permanent highlight on `agent_stop` events
- [ ] Activity events reach TUI via websocket without cache or DB re-read in the path
- [ ] DB migration renames columns without data loss
- [ ] `db.update_session()` has no `reasons` parameter
- [ ] `SessionUpdatedContext` has no `reasons` field
- [ ] `make test` and `make lint` pass
- [ ] `telec sync` succeeds
- [ ] Hooks install correctly for both agents

## Constraints

- DB migration must be backwards-compatible (rename columns, not drop/recreate)
- Existing Telegram output behavior must remain functional throughout migration
- Event bus is the fan-out mechanism — no new distribution abstractions needed
- Cache/websocket state-change path stays for session list loads and low-frequency updates

## Risks

- Stale string literal references in log messages or comments that grep misses
- Gemini `BeforeTool` may not fire in all CLI versions (verify hook works)
- `help-desk-clients` and `web-interface` todos referenced `output-streaming-unification` — updated to reference this todo

## Supersedes

- `hook-event-normalization` — absorbed entirely (event rename is Phase 4)
- `output-streaming-unification` — core intent absorbed (activity stream via event bus + websocket); distribution infrastructure (OutputDistributor, stream gateway) was over-engineered and is not needed
