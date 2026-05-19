---
id: 'project/spec/feature/session_mirrors/mirror-detail-retrieval'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Fetch one session mirror by exact or prefix session identifier and render its conversation text. Used by `telec history show` and the `/api/mirrors/{session_id}` route.'
---

# Mirror Detail Retrieval — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Operators inspect a specific past session by addressing its mirror with a
session identifier. The lookup accepts an exact match or a prefix of the
session id, with the exact match preferred when both could match. Optional
computer scoping narrows the lookup when callers supply a host name. The CLI
path renders a human-readable header (title, project, computer, start
timestamp) followed by the conversation body trimmed by an optional tail
character count. The HTTP path returns a JSON payload with session_id,
identity, title, timestamps, conversation_text, and message_count.

## Canonical fields

### Behavioral contract

#### Exact-or-prefix matching

```
Given a session_id parameter and no source_identity
When the daemon executes the mirror lookup
Then the WHERE clause matches sessions where session_id = <value> OR session_id LIKE '<value>%'
And the ordering prefers the exact match (CASE WHEN session_id = :session_id_exact THEN 0)
And ties break by shortest session_id then by updated_at DESC
And exactly one row is returned (LIMIT 1)
```

#### Source-identity lookup short-circuits

```
Given a source_identity parameter (the transcript-derived identity key)
When the daemon executes the mirror lookup
Then the WHERE clause matches source_identity = <value> exactly
And the session_id parameter is not consulted
```

#### Optional computer filter

```
Given session_id and an explicit computer name
When the daemon executes the mirror lookup
Then the WHERE clause additionally requires computer = <value>
And no fuzzy matching is performed on the computer name
```

#### CLI display rendering

```
Given an operator runs `telec history show <session-id>` and a mirror is found
When the local mirror is rendered to the terminal
Then a header is printed combining: title (if any), "Project: <project>",
  "Computer: <computer>", "Started: <timestamp_start>"
And a blank line separates header from body
And the body is the mirror's conversation_text, optionally tail-trimmed by --tail
And the body is right-stripped before printing
```

#### HTTP detail wire format

```
Given a caller issues GET /api/mirrors/{session_id}
When a mirror matches the lookup
Then the response is a JSON object with keys
  session_id, computer, agent, project, title, conversation_text,
  message_count, timestamp_start, timestamp_end
And no role-based access filtering is applied at this endpoint

Given no mirror matches the lookup
Then the route returns HTTP 404 with detail "Mirror not found"
```

#### Missing-table tolerance

```
Given the mirrors table has never been initialized on this host
When the daemon executes the mirror lookup
Then the OperationalError "no such table" is swallowed
And the function returns None (HTTP returns 404)
```

### V1 implementation pointers

- `teleclaude/mirrors/store.py:get_mirror` — exact-or-prefix WHERE clause and CASE ordering.
- `teleclaude/mirrors/store.py:_mirror_record_from_row` — row → MirrorRecord conversion.
- `teleclaude/mirrors/api_routes.py:get_mirror_route` — HTTP `/api/mirrors/{session_id}` handler.
- `teleclaude/history/search.py:show_transcript` — CLI render path including the local-mirror branch.
- `teleclaude/history/search.py:_mirror_to_display` — header + body composition with optional tail.
- `teleclaude/history/search.py:_tail_text` — character-based tail cutting (0 = unlimited).
- `teleclaude/cli/telec/handlers/history.py:_handle_history_show` — CLI argument parsing.

## Known caveats

- The HTTP detail endpoint does not apply role filtering. Callers that need
  visibility scoping must reach mirrors through the CLI or apply policy at the
  HTTP layer themselves.
- Prefix matching is inclusive of the full session id, so a short prefix can
  match many sessions; only the first row by the ordering rules is returned.
- The CLI render drops `timestamp_end` and `message_count` from the header.
  The HTTP response includes them; the terminal does not.
- When session_id is a substring (not a prefix) of a mirror's stored id, the
  detail lookup does NOT match — the LIKE pattern is `<value>%`, not
  `%<value>%`. The CLI's `find_transcript` fallback uses a separate substring
  scan over native transcripts but the mirrors table itself is prefix-only.
