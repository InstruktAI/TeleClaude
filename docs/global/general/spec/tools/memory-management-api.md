---
id: 'general/spec/tools/memory-management-api'
type: 'spec'
scope: 'global'
description: 'Canonical curl signatures for writing and retrieving memory through the daemon API.'
role: admin
---

# Memory Management API Tool — Spec

## What it is

Store and retrieve high-signal memory via the daemon API. A journal for aha-moments from user interactions.

## Canonical fields

- Transport: local unix socket (`/tmp/teleclaude-api.sock`)
- Routes: `/api/memory/`

### Save

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

### Search

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/api/memory/search?query=session+reason&limit=20&project=teleclaude"
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/api/memory/search?query=session+reason&type=decision&project=teleclaude"
```

### Delete

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock -X DELETE "http://localhost/api/memory/123"
```

### Observation types

| Type         | When to use                                                    |
| ------------ | -------------------------------------------------------------- |
| `preference` | User likes/dislikes, working style, communication preferences. |
| `decision`   | Architectural or design choices with rationale.                |
| `discovery`  | Something learned about a system, codebase, or domain.         |
| `gotcha`     | Pitfalls, traps, surprising behavior that bit us.              |
| `pattern`    | Recurring approaches that work well.                           |
| `friction`   | What causes slowdowns, miscommunication, or frustration.       |
| `context`    | Project/team/domain background knowledge.                      |
