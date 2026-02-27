# DOR Report: history-search-upgrade

## Gate Verdict: PENDING RE-ASSESSMENT

Artifacts were substantially rewritten on 2026-02-27 following a brainstorm session (3d2880de) that refined the generation architecture, corrected factual errors, and introduced new design decisions. The previous DOR score of 8 is invalidated — formal gate assessment is required against the updated artifacts.

### Changes from previous assessment

1. **Generation architecture reversed**: event-driven primary (AGENT_STOP + SESSION_CLOSED), background worker as safety net. Previous plan had worker as primary.
2. **No separate backfill script**: worker's idempotent reconciliation IS the backfill. Previous plan had `teleclaude/mirrors/backfill.py`.
3. **Fan-out architecture added**: event handlers dispatch to registered processors. Mirrors is processor #1. Extensible without rework.
4. **AGENT_STOP routing clarified**: hook event through `agent_coordinator.handle_event`, not event bus. Different wiring path than SESSION_CLOSED.
5. **SESSION_CLOSED sources corrected**: fires from `db.close_session()`, DB hard delete, `session_cleanup.replay_session_closed()`, `command_handlers` session-end. Previous artifacts incorrectly stated "Telegram-only".
6. **Function signature corrected**: `agent_name: AgentName` enum, `-> list[StructuredMessage]` return type.
7. **API route registration pinned**: `teleclaude/mirrors/api_routes.py` mounted via `app.include_router()` in `api_server.py`.
8. **Computer routing explicit**: no flag = local only, `--computer` with one or more names = parallel remote queries.
9. **Notification-service dependency added**: soft dependency — log-based fallback until notification-service is delivered. Roadmap dependency set.

### Pending gate evaluation

All 8 DOR gates must be re-evaluated against the updated requirements.md and implementation-plan.md by the gate worker.
