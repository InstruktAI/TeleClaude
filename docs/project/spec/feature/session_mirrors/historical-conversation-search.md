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

The search composes free-text terms (AND-combined), an agent filter
(`claude`, `codex`, `gemini`, comma-separated, or `all`), an optional
computer filter, and a default exclusion of dispatched-worker mirrors
(`is_worker = 0`) that a caller opts out of to search worker sessions
too. Which
commands are workers is read from the lifecycle command-role map, so
orchestrators, taskers and the integrator stay searchable — they drive
the work and carry the reasoning a later search is looking for.
Role-scoped access (see
`role-scoped-history-access`) further constrains visibility before the
store query runs. Results sort by `timestamp_start` falling back to
`updated_at`, descending, with a configurable limit (default 20).

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

#### UC-HCS-4: Dispatched-worker sessions are excluded, driving sessions are not

```
Given the mirror store holds human sessions, dispatched-worker mirrors (is_worker = 1), and orchestrator, tasker and integrator mirrors
When a search executes without the worker opt-in
Then only mirrors with is_worker = 0 are eligible for results
And sessions launched by a command the lifecycle command-role map marks a worker never appear
And orchestrator, tasker and integrator sessions are eligible like any human session
And a session launched by a command absent from that map is eligible rather than excluded
And the exclusion applies identically to the CLI path and the service search wire path

Given the caller opts in to worker sessions on the local path
When a search executes
Then the is_worker predicate is not applied and worker mirrors are eligible alongside every other mirror
And every other filter — agent, role band, limit — applies unchanged

Given the caller combines the worker opt-in with a remote computer filter
When the search is dispatched
Then the CLI refuses the combination and exits non-zero, naming the missing verified caller identity
And no remote request is issued
```

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


<!-- planned:telec-history-session-identity -->

#### UC-HCS-8: A result line states the namespace of the id it prints

```
Given a search result for a mirror that has a session record
Then the row prints that session's TeleClaude id, labelled as such
Given a search result for a mirror with a session id but no session record
Then the row prints the agent-native id, labelled as such
Given a search result for a mirror that carries no session id
Then the row prints no identifier and is marked as belonging to no addressable session
And every row carries the full project path, an agent name, and a UTC timestamp to the second
And a matched snippet is rendered on one line, with newlines replaced by spaces
```

#### UC-HCS-11: Identity and project filters, inherited from the retired listing verb

```
Given a search filtered by an identity
When the search executes
Then a mirror is eligible when the identity matches its human_email or its source identity
And that two-sided match is inherited unchanged from the retired listing filter, so a caller can name a person or a transcript identity
And the filter composes with the free-text terms rather than replacing them
And the caller's role band still applies, so the filter cannot widen what the caller may see

Given a search filtered by a project
When the search executes
Then only mirrors recorded against that project are eligible
And the project is matched against the resolved repository, not a path fragment

Given a search supplies a filter and no terms
When the search executes
Then the filter alone selects the eligible mirrors, ordered by recency
```

#### UC-HCS-9: Excluded worker matches are reported, not silently dropped

```
Given a search without the worker opt-in matches both eligible and dispatched-worker mirrors
When results are rendered
Then the excluded worker matches are reported as a count alongside the results
And the count is omitted when no worker mirror matched
```

#### UC-HCS-10: Machine output carries both ids explicitly

```
Given a caller requests machine-readable output
Then each result carries tc_id and native_id as explicit keys
And a key whose namespace has no value for that mirror is null rather than absent
And no display formatting — labels, padding, elision — appears in the machine output
```

<!-- /planned:telec-history-session-identity -->

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
