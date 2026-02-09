# Implementation Plan: Agent Logbook — Per-Agent Observability

## Objective

Add structured per-session logging via SQLite table, REST API, and MCP tool.

## Task 1: Database schema and model

**Files:**

- `teleclaude/core/db_models.py` — add `AgentLog` SQLModel.
- New migration in `teleclaude/core/migrations/` — CREATE TABLE with indexes.

Schema:

```sql
CREATE TABLE agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata TEXT,
    person TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
CREATE INDEX idx_agent_logs_session ON agent_logs(session_id);
CREATE INDEX idx_agent_logs_category ON agent_logs(category);
CREATE INDEX idx_agent_logs_timestamp ON agent_logs(timestamp);
```

**Verification:** Migration applies cleanly. Model instantiates correctly.

## Task 2: Database methods

**File:** `teleclaude/core/db.py`

- `write_log(session_id, category, message, level="info", metadata=None, person=None)` — INSERT.
- `query_logs(session_id=None, category=None, since=None, limit=20, person=None)` — SELECT with filters.

**Verification:** Unit tests for write and query with various filter combinations.

## Task 3: REST API endpoints

**File:** `teleclaude/api_server.py`

- `POST /api/logbook` — accepts `session_id`, `category`, `message`, optional `level`, `metadata`.
- `GET /api/logbook` — query params: `session_id`, `category`, `since`, `limit`, `person`.

**Verification:** API tests for write and read endpoints.

## Task 4: MCP tool

**Files:**

- `teleclaude/mcp/handlers.py` — add `teleclaude__write_log` handler.
- Tool spec with parameters: `category`, `message`, optional `level`, `metadata`.

Auto-inherits `session_id` from `caller_session_id` in tool call context.
Auto-populates `person` from session metadata if available.

**Verification:** MCP tool writes entry with correct session context.

## Task 5: Unit tests

**File:** `tests/unit/test_agent_logbook.py`

- Write log entry and verify persistence.
- Query by session_id, category, time range, person.
- Query with limit.
- MCP tool context inheritance.

## Files Changed

| File                               | Change                               |
| ---------------------------------- | ------------------------------------ |
| `teleclaude/core/db_models.py`     | Add AgentLog model                   |
| `teleclaude/core/migrations/`      | New migration                        |
| `teleclaude/core/db.py`            | Add write_log and query_logs methods |
| `teleclaude/api_server.py`         | Add logbook endpoints                |
| `teleclaude/mcp/handlers.py`       | Add write_log tool                   |
| `tests/unit/test_agent_logbook.py` | New tests                            |

## Risks

1. JSON metadata field needs validation to prevent oversized payloads. Add size limit.
2. High-frequency writes (e.g., debug logging in loops) could bloat the DB. Category-based rate limiting may be needed.

## Verification

- All tests pass.
- REST API returns correct results.
- MCP tool works within agent sessions.
