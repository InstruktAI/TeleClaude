# Agent Logbook — Per-Agent Observability — Input

## Context

All agent logging currently goes to a single namespace (`teleclaude`) and ends up in
one file: `/var/log/instrukt-ai/teleclaude/teleclaude.log`. Agents have no way to write
to their own dedicated space. The `instrukt-ai-logging` package (`get_logger(__name__)`)
writes logfmt-style key=value pairs, but this is Python logger output — agents can't
write structured entries from within their sessions.

## The Problem

- No per-session observability trail
- No way for an agent to create its own audit log
- No structured event logging that agents control
- Job runners can't write structured results to a logbook
- Security events (blocked messages, prompt injection attempts) have nowhere clean to go
- The web interface needs a data source for security reports and admin dashboards

## The Feature

Give agents a writing capability to their own logbook space. Each agent session gets
(or can request) a logbook that persists beyond the session and is queryable by humans
and other agents.

### What agents could log

- Security events: blocked input, sanitization flags, suspicious patterns
- Decision trails: why a tool was chosen, what was considered and rejected
- Job execution results: structured output from cron jobs
- Performance observations: timing, token usage, retry counts
- Error context: what the agent was doing when something went wrong

### Shape

SQLite table in the existing `teleclaude.db`:

```sql
CREATE TABLE agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,           -- ISO 8601
    level TEXT NOT NULL DEFAULT 'info', -- debug, info, warning, error
    category TEXT NOT NULL,            -- security, decision, job_result, performance, error
    message TEXT NOT NULL,
    metadata TEXT,                     -- JSON object
    person TEXT,                       -- resolved from session metadata
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX idx_agent_logs_session ON agent_logs(session_id);
CREATE INDEX idx_agent_logs_category ON agent_logs(category);
CREATE INDEX idx_agent_logs_timestamp ON agent_logs(timestamp);
```

### API

- **Write**: `POST /api/logbook` — agents write structured entries via MCP tool or
  direct API call. Requires `session_id`, `category`, `message`. Optional `level`,
  `metadata`.
- **Read**: `GET /api/logbook?session_id=...&category=security&since=...&limit=20` —
  humans and agents query logbooks. Filterable by session, category, time range, person.
- **MCP tool**: `teleclaude__write_log` — new MCP tool for agents to write to their
  logbook from within sessions. Auto-inherits session_id and person from session metadata.

### Namespace isolation

Each entry is scoped by `session_id` and `person`. Queries can aggregate across
sessions (all security events for a person) or drill into a single session's trail.

## Relationship to Other Work

- **web-interface**: security reports and admin dashboards need the logbook as data source
- **job runners**: jobs need structured result logging
- **input sanitization**: blocked messages need to be logged somewhere queryable
- **person-identity-auth**: admin views should include security event dashboards

## Dependencies

None — this is a standalone daemon feature. Can be built independently.

## Out of Scope

- Log rotation / retention policies (use SQLite VACUUM or simple age-based DELETE)
- External log shipping (Datadog, etc.)
- Real-time log streaming (query-based is sufficient for v1)
