---
id: 'project/spec/feature/session_mirrors/historical-mirror-listing'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'List recent session mirrors with optional identity, project, and role filters. Used by `telec history list` to surface stored conversations in recency order with a summary column.'
---

# Historical Mirror Listing — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Operators enumerate stored session mirrors through `telec history list`. The
command renders a tab-separated row per mirror with session id, title, start
and end timestamps, the origin channel (when known), a short summary, and the
message count. Three optional filters narrow the listing: `--identity`
(matches `human_email` OR `source_identity`), `--project` (matches the
mirror's project string), and `--limit` (default 20). Role-scoped access
further restricts visibility before SQL execution (see
`role-scoped-history-access`).

## Canonical fields

### Behavioral contract

#### Identity filter applies to both columns

```
Given an operator runs `telec history list --identity <value>`
When the daemon executes the listing query
Then the WHERE clause includes (human_email = <value> OR source_identity = <value>)
And both columns are compared without case-folding
```

#### Project filter is exact-match

```
Given an operator runs `telec history list --project <value>`
When the daemon executes the listing query
Then the WHERE clause includes project = <value>
And no glob or prefix matching is applied
```

#### Recency ordering with limit

```
Given any combination of filters (or none)
When the daemon executes the listing query
Then rows are ordered by COALESCE(timestamp_start, updated_at) DESC
And the result count is capped at the --limit value (default 20)
```

#### Terminal rendering

```
Given a non-empty result list
When the CLI renders the listing
Then each row prints as
  <session_id>\t<title>\t<timestamp_start_or_blank>\t<timestamp_end_or_blank>\t<origin_channel_or_blank>\t<summary>\t<message_count>
And origin_channel is read from the mirror's metadata.origin_channel field
And summary defaults to the title when no summary is stored
And summary is truncated to 77 chars + "..." when longer than 80 chars
And an empty result list prints "No session mirrors found."
```

#### Missing-table tolerance

```
Given the mirrors table has never been initialized on this host
When the daemon executes the listing query
Then the OperationalError "no such table" is swallowed
And the listing renders "No session mirrors found."
```

### V1 implementation pointers

- `teleclaude/mirrors/store.py:list_mirrors` — SQL builder with optional identity/project clauses.
- `teleclaude/mirrors/store.py:_mirror_record_from_row` — row → MirrorRecord conversion (includes summary, human_email, visibility, metadata).
- `teleclaude/cli/telec/handlers/history.py:_handle_history_list` — argument parsing and per-row rendering.
- `teleclaude/cli/telec/handlers/history.py:resolve_cli_caller_role` — terminal identity → role lookup used by the role filter.

## Known caveats

- `--identity` does not match `caller_email`; it matches the mirror's stored
  `human_email` or the transcript-derived `source_identity`. A caller's own
  authenticated identity is set separately by `caller_email` for the role
  filter, not by this option.
- The renderer does not show `human_email` even to admins — only summary,
  title, timestamps, origin channel, and message count. Admin-only rendering
  of human_email is implemented for search/show paths, not the listing.
- `origin_channel` is read from the metadata blob; mirrors created before
  channel-identifier enrichment landed will render an empty origin column.
- The listing is local-host only — there is no `--computer` fan-out for
  `telec history list`. Cross-computer fan-out is exposed for search and show
  only.
