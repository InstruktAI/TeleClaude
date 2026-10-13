---
description: "Full-text search across stored session mirrors. Operators query past conversations by text via CLI or via the session_mirrors service's search capability and get a recency-sorted hit list with a query-centered snippet per row."
visibility: 'public'
---

# Historical Conversation Search — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md
- @docs/local/spec/domain/context-map.md

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
<!-- planned-change:procedure-role-capability-composition -->

(`is_worker = 0`) that a caller opts out of to search worker sessions
too. Whether a mirror is a worker is the system role its session record
carries, so orchestrators, taskers and the integrator stay searchable —
they drive the work and carry the reasoning a later search is looking
for. Subagent transcripts are never mirrored, so they cannot appear.
<!-- change:procedure-role-capability-composition -->

(`is_worker = 0`) that a caller opts out of to search worker sessions
too. Whether a mirror is a worker is whether the role its session record
carries is of the worker class in the agent role catalog
(`local/projects/teleclaude/spec/feature/identity/agent-roles`), so
orchestrators, task-lane sessions and the integrator stay searchable — they
drive the work and carry the reasoning a later search is looking for.
Subagent transcripts are never mirrored, so they cannot appear.
<!-- /planned-change:procedure-role-capability-composition -->

Role-scoped access (see
`role-scoped-history-access`) further constrains visibility before the
store query runs. Results sort by `timestamp_start` falling back to
`updated_at`, descending, with a configurable limit (default 20).

## Canonical fields

### Session-owned search results

Search indexes the complete mirror owned by a TeleClaude session. Matching
several source segments returns one conversation result. Existing agent and
source selectors read source provenance without multiplying that result.
Native references remain source aliases under
`local/projects/teleclaude/spec/feature/session_mirrors/session-id-namespaces`.
Existing history reach and worker/subagent selection rules remain applicable.

### Use cases

#### Term composition and full-text match

```
Given a search query of one or more whitespace-separated terms
When the session_mirrors service builds the match expression
Then each term is treated as a literal phrase (internal quotes escaped)
And the terms are AND-joined into a single match expression
And an empty or whitespace-only query with no selector returns no rows without invoking the index
And an empty query accompanied by an identity or project selector is a selector-only search, which selects by that filter and orders by recency without invoking the index
```

#### CLI search rendering

```
Given an operator runs `telec history search <terms>`
When the local mirror search returns one or more hits
Then the terminal prints a header "Search results for '<terms>' (<n> found):"
And each hit prints as two lines: a metadata line, then its matched snippet indented beneath
And the metadata line carries the UTC timestamp to the second, the agent, the labelled identifier, and the full project path
And the row's snippet prefers the full-text match, falling back to the title, then to the first 70 characters of the conversation
And no index column and no revive footer are printed
And no rows print "No conversations found matching '<terms>' across <agents>"
```

#### Service search wire format

```
Given a caller invokes the search capability with q=<query>, agent=<filter>, limit=<n>, and optionally identity=<value> and project=<value>
And the identity and project selectors compose with the query rather than replacing it
And a request carrying a selector and an empty query is a selector-only search
When the service resolves the agent filter
Then the response is a sequence of rows with fields
  session_id, computer, agent, project, title, sort_timestamp, timestamp, topic
And the rows are those within the caller's history scope
And an unknown agent value is rejected with a validation error referencing the unknown value
And limit is clamped to the inclusive range [1, 100]

Given a caller the capability cannot identify
Then the capability refuses the request before any mirror is read
```

#### UC-HCS-4: Dispatched-worker sessions are excluded, driving sessions are not

<!-- planned-change:procedure-role-capability-composition -->

```
Given the mirror store holds human sessions, dispatched-worker mirrors (is_worker = 1), and orchestrator, tasker and integrator mirrors
When a search executes without the worker opt-in
Then only mirrors with is_worker = 0 are eligible for results
And a session whose record carries the worker system role never appears
And orchestrator, tasker and integrator sessions are eligible like any human session
And a session with no record, or a record carrying any other role, is eligible rather than excluded
And the exclusion applies identically to the CLI path and the service search wire path

Given the caller opts in to worker sessions on the local path
When a search executes
Then the is_worker predicate is not applied and worker mirrors are eligible alongside every other mirror
And every other filter — agent, role band, limit — applies unchanged
```

<!-- change:procedure-role-capability-composition -->

```
Given the mirror store holds human sessions, dispatched-worker mirrors (is_worker = 1), and orchestrator, task-lane and integrator mirrors
When a search executes without the worker opt-in
Then only mirrors with is_worker = 0 are eligible for results
And a session whose record carries a worker-class role never appears
And orchestrator, task-lane and integrator sessions are eligible like any human session
And a session with no record, or a record carrying a role of another class, is eligible rather than excluded
And the exclusion applies identically to the CLI path and the service search wire path

Given the caller opts in to worker sessions on the local path
When a search executes
Then the is_worker predicate is not applied and worker mirrors are eligible alongside every other mirror
And every other filter — agent, role band, limit — applies unchanged
```

<!-- /planned-change:procedure-role-capability-composition -->

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

#### UC-HCS-8: A result line states the namespace of the id it prints

```
Given a search result for a mirror attributed to a TeleClaude session
Then the row prints that session's TeleClaude id, labelled as such
And this holds across the session's full transcript chain and after runtime closure or soft deletion
Given a search result for a mirror no session is attributed to
Then the row prints the agent-native id, labelled as such
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

#### UC-HCS-12: History search returns canonical semantic conversations

```gherkin
Given stored mirrors contain authored conversation alongside runtime-provided startup context
And more than one stored mirror rendering represents the same agent-native conversation
And more than one TeleClaude session record is associated with that conversation
And a mirror written during a producer upgrade carries a legacy non-UUID identity
When an operator searches historical conversations with a result limit
Then terms occurring only in runtime-provided context do not make a conversation match
And each TeleClaude conversation contributes exactly one result across its native transcript lineage
And duplicate renderings are collapsed before the result limit is applied
And the canonical result page is ordered by conversation recency after collapsing duplicates
And the result displays the retained TeleClaude conversation identity
And the legacy mirror identity is reconciled from its transcript and cannot be restored by a subsequent stale producer write
And a conversation with no TeleClaude association retains its labelled agent-native identifier
```

#### UC-HCS-13: Quoted dash-leading search text

```gherkin
Given a human operator searches historical conversations for '--human-approved'
When the operator supplies that search text in either single or double shell quotes
Then the search runs using that text rather than rejecting it as an unknown option
And the operator receives the matching conversations or the normal no-results response
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
