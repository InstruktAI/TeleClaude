---
description: "Full-text search across stored session mirrors. Operators query past conversations by text via CLI or via the session_mirrors service's search capability and get a recency-sorted hit list with a query-centered snippet per row."
visibility: 'public'
---

# Historical Conversation Search — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/context-map.md

## What it is

Operators searching for past agent conversations rely on full-text search
over the local session_mirrors store. Every stored mirror's conversation
text is indexed by a full-text index, and queries return one row per
matching mirror with a 12-token snippet centered on the matched terms. The
capability is exposed both through `telec history search` on the command
line and through the session_mirrors service's search capability that the
cross-computer federation layer calls.

<!-- planned-change:clean-mirror-search-index -->

The search composes three filters: free-text terms (AND-combined), an agent
filter (`claude`, `codex`, `gemini`, comma-separated, or `all`), and an
optional computer filter. Role-scoped access (see
`role-scoped-history-access`) further constrains visibility before the
store query runs. Results sort by `timestamp_start` falling back to
`updated_at`, descending, with a configurable limit (default 20).

<!-- change:clean-mirror-search-index -->

The search composes free-text terms (AND-combined), an agent filter
(`claude`, `codex`, `gemini`, comma-separated, or `all`), an optional
computer filter, and a default exclusion of agent-spawn mirrors
(`is_agent_spawn = 0`) so dispatched worker/orchestrator/integrator
sessions never appear in human search. Role-scoped access (see
`role-scoped-history-access`) further constrains visibility before the
store query runs. Results sort by `timestamp_start` falling back to
`updated_at`, descending, with a configurable limit (default 20).

<!-- /planned-change:clean-mirror-search-index -->

## Canonical fields

### Use cases

#### Term composition and full-text match

```
Given a search query of one or more whitespace-separated terms
When the session_mirrors service builds the match expression
Then each term is treated as a literal phrase (internal quotes escaped)
And the terms are AND-joined into a single match expression
And an empty or whitespace-only query returns no rows without invoking the index
```

#### CLI search rendering

```
Given an operator runs `telec history search <terms>`
When the local mirror search returns one or more hits
Then the terminal prints a header "Search results for '<terms>' (<n> found):"
And each row prints as: index | timestamp | agent | project | topic | session_id
And the row's topic prefers the full-text snippet, falling back to the title, then to the first 70 characters of the conversation
And a final line prints "Revive: telec sessions revive <session-id> --agent <agent>"
And no rows print "No conversations found matching '<terms>' across <agents>"
```

#### Service search wire format

```
Given a caller invokes the search capability with q=<query>, agent=<filter>, limit=<n>
When the service resolves the agent filter
Then the response is a sequence of rows with fields
  session_id, computer, agent, project, title, sort_timestamp, timestamp, topic
And an unknown agent value is rejected with a validation error referencing the unknown value
And limit is clamped to the inclusive range [1, 100]
```

<!-- planned:clean-mirror-search-index -->

#### Agent-spawn sessions excluded by default

```
Given the mirror store holds both human sessions and agent-spawn mirrors (is_agent_spawn = 1)
When a search executes
Then only mirrors with is_agent_spawn = 0 are eligible for results
And dispatched worker/orchestrator/integrator sessions never appear
And the exclusion applies identically to the CLI path and the service search wire path
```

<!-- /planned:clean-mirror-search-index -->

#### Recency ordering and missing-store tolerance

```
Given the mirror store holds rows
When the search executes
Then results are ordered by COALESCE(timestamp_start, updated_at) descending
And the result count is capped at the requested limit (default 20)

Given the mirror store has never been initialized on this host
When the search executes
Then the missing-store condition is swallowed
And the call returns an empty result set
```

## Known caveats

- The full-text snippet uses a fixed window of 12 tokens with empty
  start/end markers and `…` as the truncation marker. Long matches show
  only a narrow window.
- Term composition is AND-only across terms; OR / NEAR / column filters
  are not exposed.
- Limit is enforced once at the store boundary and once when rendering
  remote results; values above 100 are rejected at the service boundary
  but the CLI does not pre-validate.
- Result ordering treats sessions with no `timestamp_start` and no
  `updated_at` as zero-valued, sorting them last. Such rows can only arise
  from corrupt mirror writes.
