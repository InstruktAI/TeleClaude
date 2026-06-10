---
description: OpenCode session and message storage (SQLite)
---

# OpenCode Session Storage

## Data root

`~/.local/share/opencode/` (override via `OPENCODE_DATA_DIR`):

- `opencode.db` (+ `-wal`, `-shm`) — SQLite, WAL mode, Drizzle ORM. Holds sessions,
  messages, and parts.
- `auth.json` — provider credentials / OAuth tokens.
- `storage/session_diff/{sessionID}.json`, `storage/migration/`, `snapshot/`, `repos/`, `log/`.

## Schema

`session`:

```
id            text PK        -- "ses_19b34d97cffezGll5HI62wnTcR"
project_id    text NOT NULL  -- hash, FK -> project.id (matches snapshot dir name)
parent_id     text           -- parent session id; non-null = subagent
slug          text
directory     text           -- project path, e.g. /Users/.../TeleClaude
title         text
agent         text           -- e.g. "build"
model         text           -- JSON: {"id":"claude-opus-4-7","providerID":"opencode","variant":"default"}
cost real, tokens_input/output/reasoning/cache_read/cache_write integer
time_created  integer        -- epoch ms
time_updated  integer
time_compacting, time_archived integer
workspace_id, path, version, share_url text
```

`message`:

```
id            text PK        -- "msg_..."
session_id    text NOT NULL  -- FK -> session.id, ON DELETE CASCADE
time_created  integer        -- epoch ms
time_updated  integer
data          text NOT NULL  -- JSON (below)
```

`message.data` (assistant message):

```json
{
  "parentID": "msg_...",
  "role": "assistant",
  "mode": "build",
  "agent": "build",
  "path": { "cwd": "/abs/path", "root": "/abs/path" },
  "cost": 0,
  "tokens": { "total": 28151, "input": 28129, "output": 2, "reasoning": 20, "cache": { "write": 0, "read": 0 } },
  "modelID": "big-pickle",
  "providerID": "opencode",
  "time": { "created": 1779808022899, "completed": 1779808025998 },
  "finish": "stop"
}
```

`part` (a message has many parts):

```
id            text PK        -- "prt_..."
message_id    text NOT NULL  -- FK -> message.id, ON DELETE CASCADE
session_id    text NOT NULL  -- FK -> session.id
time_created  integer        -- epoch ms
time_updated  integer
data          text NOT NULL  -- JSON, type-tagged
```

`part.data` `type` values: `text`, `reasoning`, `step-start`, `step-finish`.

- `text`: `{"type":"text","text":"...","synthetic":bool,"metadata":{...}}`
- `step-finish`: `{"type":"step-finish","reason":"stop","snapshot":"<sha>","tokens":{...},"cost":0}`

A session's transcript is the parts joined to messages:
`part ⋈ message ON part.message_id = message.id WHERE message.session_id = ?
ORDER BY message.time_created, part.time_created`.

Project name resolves via `session.project_id → project.name`, or the `session.directory`
column. Subagent linkage is `session.parent_id`.

Other tables: `project`, `permission`, `todo`, `workspace`, `session_share`,
`session_message`, `event`, `event_sequence`.

OpenCode holds the DB open in WAL mode; external reads use a read-only connection
(`mode=ro`, `PRAGMA query_only`).

## Sources

- https://opencode.ai/docs/troubleshooting/

(Schema and JSON shapes verified against a live `~/.local/share/opencode/opencode.db`,
OpenCode 1.15.10.)
