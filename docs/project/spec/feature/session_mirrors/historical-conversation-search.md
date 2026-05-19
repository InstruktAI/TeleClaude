---
id: 'project/spec/feature/session_mirrors/historical-conversation-search'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Full-text search across stored session mirrors. Operators query past conversations by text via CLI or HTTP and get a recency-sorted hit list with a query-centered snippet per row.'
---

# Historical Conversation Search — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/context-map.md

## What it is

Operators searching for past agent conversations rely on full-text search over
the local mirrors database. Every stored mirror's conversation text is indexed
by an FTS5 virtual table, and queries return one row per matching mirror with
a 12-token snippet centered on the matched terms. The capability is exposed
through both `telec history search` on the command line and a `GET
/api/mirrors/search` HTTP endpoint that the cross-computer federation layer
calls.

The search composes three filters: free-text terms (AND-combined, double-quote
wrapped to escape internal quotes), an agent filter (`claude`, `codex`,
`gemini`, comma-separated, or `all`), and an optional computer filter passed
through to SQL when present. Role-scoped access (see
`role-scoped-history-access`) further constrains visibility before SQL
execution. Results sort by `timestamp_start` falling back to `updated_at`,
descending, with a configurable limit (default 20).

## Canonical fields

### Behavioral contract

#### Term composition and FTS5 match

```
Given a search query of one or more whitespace-separated terms
When the daemon builds the FTS5 MATCH expression
Then each term is double-quoted (with internal quotes escaped by doubling)
And the terms are AND-joined into a single MATCH string
And an empty or whitespace-only query returns no rows without hitting SQLite
```

#### CLI search rendering

```
Given an operator runs `telec history search <terms>`
When the local mirrors search returns one or more hits
Then the terminal prints a header "Search results for '<terms>' (<n> found):"
And each row prints as: index | timestamp | agent | project | topic | session_id
And the row's topic prefers the FTS5 snippet, falling back to the title, then to the first 70 characters of the conversation
And a final line prints "Revive: telec sessions revive <session-id> --agent <agent>"
And no rows print "No conversations found matching '<terms>' across <agents>"
```

#### HTTP search wire format

```
Given a caller issues GET /api/mirrors/search with q=<query>, agent=<filter>, limit=<n>
When the route handler resolves the agent filter
Then the response is a JSON array of rows with keys
  session_id, computer, agent, project, title, sort_timestamp, timestamp, topic
And an unknown agent value returns HTTP 400 with "Unknown agent filter: <value>"
And limit is clamped to the range [1, 100] by FastAPI's Query validation
```

#### Recency ordering and missing-table tolerance

```
Given the mirrors table exists with rows
When the search query executes
Then results are ordered by COALESCE(timestamp_start, updated_at) DESC
And the result count is capped at the requested limit (default 20)

Given the mirrors table has never been initialized on this host
When the search query executes
Then the OperationalError "no such table" is swallowed
And the call returns an empty result list (HTTP returns [])
```

### V1 implementation pointers

- `teleclaude/mirrors/store.py:search_mirrors` — SQL builder, FTS5 MATCH composition, role filter integration.
- `teleclaude/mirrors/store.py:_match_query` — term quoting and AND-join.
- `teleclaude/mirrors/store.py:_topic_for_row` — snippet/title/conversation fallback chain.
- `teleclaude/mirrors/store.py:_format_search_timestamp` — local-time rendering of `sort_timestamp`.
- `teleclaude/mirrors/api_routes.py:search_mirror_routes` — HTTP `/api/mirrors/search` handler.
- `teleclaude/mirrors/api_routes.py:_parse_agent_filter` — `all` / comma-separated agent parsing.
- `teleclaude/history/search.py:display_combined_history` — CLI terminal rendering path.
- `teleclaude/history/search.py:_print_results` — per-row header and revive hint.
- `teleclaude/cli/telec/handlers/history.py:_handle_history_search` — CLI argument parsing and identity resolution.

## Known caveats

- FTS5 snippet uses a fixed window of 12 tokens with empty start/end markers and `…` as the truncation marker. Long matches show only a narrow window.
- The MATCH expression uses AND semantics across terms; OR / NEAR / column filters are not exposed.
- Limit is enforced once in SQL and once when rendering remote results; values above 100 are rejected at the HTTP boundary but the CLI does not pre-validate.
- Result ordering treats sessions with no `timestamp_start` and no `updated_at` as zero-valued, sorting them last. Such rows can only arise from corrupt mirror writes.
