# Requirements: Agent Logbook — Per-Agent Observability

## Goal

Give agents a structured logging capability to their own logbook space via SQLite, with write API, read API with filtering, and an MCP tool. Each entry is scoped by session_id and person for namespace isolation.

## Problem Statement

All agent logging goes to a single Python logger output (`teleclaude.log`). Agents have no way to create structured audit entries from within sessions. Security events, decision trails, job results, and performance data have nowhere clean and queryable to go.

## Scope

### In scope

1. **SQLite table** `agent_logs` in existing `teleclaude.db`.
2. **Write API** — `POST /api/logbook` for agents to write structured entries.
3. **Read API** — `GET /api/logbook` with filtering by session, category, time range, person.
4. **MCP tool** — `teleclaude__write_log` for agents to write from within sessions.
5. **Namespace isolation** — entries scoped by `session_id` and `person`.
6. **Indexes** for session_id, category, and timestamp.

### Out of scope

- Log rotation / retention policies.
- External log shipping (Datadog, etc.).
- Real-time log streaming.
- Web UI for viewing logs (web-interface todo).

## Functional Requirements

### FR1: Database schema

- Table `agent_logs` with columns: `id` (autoincrement), `session_id` (FK), `timestamp` (ISO 8601), `level` (debug/info/warning/error), `category` (security/decision/job_result/performance/error), `message` (text), `metadata` (JSON), `person` (resolved from session).
- Indexes on `session_id`, `category`, `timestamp`.

### FR2: Write API

- `POST /api/logbook` — requires `session_id`, `category`, `message`. Optional: `level` (default "info"), `metadata` (JSON object).
- `person` field auto-resolved from session metadata (when person-identity-auth is available).

### FR3: Read API

- `GET /api/logbook` with query parameters: `session_id`, `category`, `since` (ISO timestamp), `limit` (default 20), `person`.
- Returns list of log entries with all fields.
- Supports aggregation across sessions (all security events for a person).

### FR4: MCP tool

- `teleclaude__write_log` tool exposed via MCP.
- Auto-inherits `session_id` from caller context.
- Parameters: `category`, `message`, optional `level`, optional `metadata`.
- `person` auto-populated from session if available.

## Non-functional Requirements

1. Write operations must be fast (INSERT only, no reads during write).
2. Read queries must be indexed for common access patterns.
3. Metadata field accepts arbitrary JSON for extensibility.

## Acceptance Criteria

1. `agent_logs` table created with correct schema and indexes.
2. `POST /api/logbook` writes entries with all required fields.
3. `GET /api/logbook` returns filtered results correctly.
4. MCP tool writes entries with auto-inherited session_id.
5. Person field populated when session has identity binding.
6. All existing tests pass.

## Dependencies

- None (standalone feature). Person field is optional until person-identity-auth is delivered.
