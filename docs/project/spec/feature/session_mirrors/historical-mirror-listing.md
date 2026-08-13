---
description: 'List recent session mirrors with optional identity, project, and role filters. Used by `telec history list` to surface stored conversations in recency order with a summary column.'
visibility: 'public'
---

# Historical Mirror Listing — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

Operators enumerate stored session mirrors through `telec history list`. The
command renders a tab-separated row per mirror with session id, title,
start and end timestamps, the origin channel (when known), a short
summary, and the message count. Three optional filters narrow the
listing: `--identity` (matches `human_email` OR `source_identity`),
`--project` (matches the mirror's project string), and `--limit`
(default 20). Role-scoped access further restricts visibility before the
listing executes (see `role-scoped-history-access`).

## Canonical fields

### Use cases

#### Identity filter applies to both columns

```
Given an operator runs `telec history list --identity <value>`
When the session_mirrors service executes the listing
Then the listing matches mirrors whose human_email = <value> OR source_identity = <value>
And both fields are compared case-sensitively
```

#### Project filter is exact-match

```
Given an operator runs `telec history list --project <value>`
When the session_mirrors service executes the listing
Then the listing matches mirrors whose project equals <value> exactly
And no glob or prefix matching is applied
```

#### Recency ordering with limit

```
Given any combination of filters (or none)
When the session_mirrors service executes the listing
Then rows are ordered by COALESCE(timestamp_start, updated_at) descending
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
And summary is truncated to 77 characters + "..." when longer than 80 characters
And an empty result list prints "No session mirrors found."
```

#### Missing-store tolerance

```
Given the mirror store has never been initialized on this host
When the session_mirrors service executes the listing
Then the missing-store condition is swallowed
And the listing renders "No session mirrors found."
```


<!-- planned:telec-history-session-identity -->

#### UC-HML-4: The listing verb is retired

```
Given an operator invokes the listing verb
Then no such command exists on the history surface
And enumerating stored mirrors for one identity is served by search's identity filter
And enumerating live and closed sessions is served by the sessions surface
```

<!-- /planned:telec-history-session-identity -->

## Known caveats

- `--identity` does not match `caller_email`; it matches the mirror's
  stored `human_email` or the transcript-derived `source_identity`. A
  caller's own authenticated identity is set separately by `caller_email`
  for the role filter, not by this option.
- The renderer does not show `human_email` even to admins — only summary,
  title, timestamps, origin channel, and message count. Admin-only
  rendering of `human_email` is implemented for the search/show paths,
  not the listing.
- `origin_channel` is read from the metadata blob; mirrors created before
  channel-identifier enrichment landed will render an empty origin column.
- The listing is local-host only — there is no `--computer` fan-out for
  `telec history list`. Cross-computer fan-out is exposed for search and
  show only.
