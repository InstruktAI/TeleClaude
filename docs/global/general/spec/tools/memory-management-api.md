---
id: 'general/spec/tools/memory-management-api'
type: 'spec'
scope: 'global'
description: 'Canonical curl signatures for writing and retrieving memory through the daemon API.'
---

# Memory Management API Tool — Spec

## What it is

Defines canonical HTTP signatures for storing and retrieving high-signal memory via the daemon API.

## Canonical fields

- Transport: local unix socket (`/tmp/teleclaude-api.sock`)
- Routes are mounted under `/api/memory/` on the daemon's FastAPI app.
- Default project tag: `teleclaude` (or active project slug)
- Save memory:

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock -X POST "http://localhost/api/memory/save" \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Root cause identified for session update reason suppression.",
    "title": "Session reason fix",
    "type": "discovery",
    "project": "teleclaude"
  }'
```

- Search:

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/api/memory/search?query=session+reason&limit=20&project=teleclaude"
```

- Search with type filter (progressive disclosure):

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/api/memory/search?query=session+reason&type=decision&project=teleclaude"
```

- Timeline context:

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/api/memory/timeline?anchor=123&depth_before=3&depth_after=3&project=teleclaude"
```

- Batch fetch:

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock -X POST "http://localhost/api/memory/batch" \
  -H 'Content-Type: application/json' \
  -d '{"ids":[123,124],"project":"teleclaude"}'
```

## Observation types

| Type         | When to use                                                    |
| ------------ | -------------------------------------------------------------- |
| `preference` | User likes/dislikes, working style, communication preferences. |
| `decision`   | Architectural or design choices with rationale.                |
| `discovery`  | Something learned about a system, codebase, or domain.         |
| `gotcha`     | Pitfalls, traps, surprising behavior that bit us.              |
| `pattern`    | Recurring approaches that work well.                           |
| `friction`   | What causes slowdowns, miscommunication, or frustration.       |
| `context`    | Project/team/domain background knowledge.                      |

## Allowed values

- `query`: free text.
- `limit`: positive integer (1-100, default 20).
- `anchor`: observation ID.
- `depth_before`, `depth_after`: non-negative integers (max 20).
- `ids`: non-empty integer list.
- `project`: project identifier string.
- `type`: observation type string (optional filter on search).

## Known caveats

- Prefer progressive narrowing (`search`/`timeline`) before `batch` to control noise.
- Store only durable, high-signal memory; avoid routine chatter.
- Never include secrets, credentials, or sensitive personal data in payloads.
- The daemon must be running for the unix socket to be available.
