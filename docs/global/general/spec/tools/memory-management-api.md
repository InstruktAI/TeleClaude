---
id: 'general/spec/tools/memory-management-api'
type: 'spec'
scope: 'global'
description: 'Canonical curl signatures for writing and retrieving memory through the external worker API.'
---

# Memory Management API Tool — Spec

## What it is

Defines canonical HTTP signatures for storing and retrieving high-signal memory via the external worker API.

## Canonical fields

- Base URL: `http://127.0.0.1:37777` (recommended env: `MEM_BASE_URL`)
- Default project tag: `teleclaude` (or active project slug)
- Canonical setup:

```bash
export MEM_BASE_URL="http://127.0.0.1:37777"
```

- Save memory:

```bash
curl -s -X POST "$MEM_BASE_URL/api/memory/save" \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Root cause identified for session update reason suppression.",
    "title": "Session reason fix",
    "project": "teleclaude"
  }'
```

- Search:

```bash
curl -s "$MEM_BASE_URL/api/search?query=session+reason&limit=20&project=teleclaude"
```

- Timeline context:

```bash
curl -s "$MEM_BASE_URL/api/timeline?anchor=123&depth_before=3&depth_after=3&project=teleclaude"
```

- Batch fetch:

```bash
curl -s -X POST "$MEM_BASE_URL/api/observations/batch" \
  -H 'Content-Type: application/json' \
  -d '{"ids":[123,124],"project":"teleclaude"}'
```

## Allowed values

- `query`: free text.
- `limit`: positive integer.
- `anchor`: observation ID.
- `depth_before`, `depth_after`: non-negative integers.
- `ids`: non-empty integer list.
- `project`: project identifier string.

## Known caveats

- Prefer progressive narrowing (`search`/`timeline`) before `observations/batch` to control noise.
- Store only durable, high-signal memory; avoid routine chatter.
- Never include secrets, credentials, or sensitive personal data in payloads.
