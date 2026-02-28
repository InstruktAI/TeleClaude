# Input: event-platform-core

Phase 1 of the event processing platform. This sub-todo delivers the foundation: separate
`teleclaude_events/` package, five-layer envelope schema, pipeline runtime with pluggable
cartridges, deduplication + notification projector cartridges, Redis Streams ingress,
SQLite notification state, HTTP API, WebSocket push, Telegram delivery adapter, daemon
hosting, initial event schemas, `telec events list` CLI, and consolidation of the old
notification system.

The full platform vision (all 7 phases) was documented in the former `event-platform/`
holder todo, accessible via git history (commit range around 2026-02-28). The "Out of scope"
section in this todo's `requirements.md` lists what later phases deliver.
