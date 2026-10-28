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
(`claude`, `codex`, `gemini`, `deepseek`, comma-separated, or `all`), an optional
computer filter, and a default exclusion of focused-role mirrors

(`is_worker = 0`) that a caller opts out of to search focused-role sessions
too. Whether a mirror is a focused-role mirror is whether the role its session record
carries is of the focused class in the agent role catalog
(`local/projects/teleclaude/spec/feature/identity/agent-roles`), so
orchestrators, task-lane sessions and the integrator stay searchable — they
drive the work and carry the reasoning a later search is looking for.
Subagent transcripts are never mirrored, so they cannot appear.
The default focused-role exclusion is the same on the terminal and service search
paths. The local CLI opt-in removes only that exclusion; the other search
filters and role-scoped access remain in effect.

An unrecognized agent filter is rejected with a validation error naming the filter.

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
Existing history reach and focused-role/subagent selection rules remain applicable.
An empty text query without an identity or project selector returns no rows.

### Use cases

#### UC-HCS-4: An operator can choose whether history search includes focused-role sessions

```gherkin
Scenario: Include focused-role conversations in a history search
  Given an operator searches history for a term present in a focused-role conversation
  When the operator opts to include focused-role conversations on the local CLI
  Then matching focused-role conversations appear alongside other matching conversations
  And the other search filters continue to apply

Scenario: Understand focused-role conversations excluded from results
  Given an operator searches without focused-role inclusion
  And matching conversations include focused-role and other conversations
  When the search results are shown
  Then the operator sees how many focused-role matches were excluded
  And no excluded focused-role count is shown when no focused-role conversation matched
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

#### UC-HCS-8: An operator can identify the address of a history result

```gherkin
Scenario: Identify a result attributed to a TeleClaude session
  Given an operator reviews a history result attributed to a TeleClaude session
  When the operator inspects its identifier
  Then the result displays that TeleClaude id labelled as such

Scenario: Identify a result with no session attribution
  Given an operator reviews a history result with no TeleClaude session association
  When the operator inspects its identifier
  Then the result displays the agent-native id labelled as such
```

#### UC-HCS-11: An operator finds past conversations for an identity or project

```gherkin
Scenario Outline: Find conversations within an identity or project
  Given an operator wants to find stored conversations for <scope>
  When the operator searches history with <selector> and <terms>
  Then the results include only <matching mirrors>
  And the caller's role band still limits which mirrors are returned
  And the selector composes with any free-text terms
  And when no terms are supplied, the selector alone returns results in recency order

  Examples:
    | scope                | selector       | terms       | matching mirrors                                                                     |
    | a person             | an identity    | "invoice"  | whose human_email or source identity matches                                        |
    | a transcript identity| an identity    | "invoice"  | whose human_email or source identity matches                                        |
    | a project            | a project      | "invoice"  | recorded against the resolved repository, not a path fragment                      |
    | a person             | an identity    | no terms    | whose human_email or source identity matches                                        |
    | a project            | a project      | no terms    | recorded against the resolved repository, not a path fragment                      |
```

#### UC-HCS-9: Excluded focused-role matches are reported, not silently dropped

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

#### UC-HCS-13: An operator finds past conversations by text

```gherkin
Scenario: Find conversations matching a text term
  Given an operator wants to find past conversations containing a term
  When the operator searches history for that term
  Then matching conversations are returned with their labelled identity and query-centered snippet
  And the ordinary no-results response is returned when nothing matches

Scenario: Search for text that resembles a command option
  Given an operator wants to find past conversations containing '--human-approved'
  When they provide that term in single or double shell quotes
  Then the search uses the term as text and returns matches or the ordinary no-results response
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
