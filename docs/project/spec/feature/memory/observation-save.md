---
description: 'Save a memory observation — auto-titled, default-project-scoped, identity-tagged, and slotted into a per-project manual session.'
visibility: 'public'
---

# Observation Save — Spec

## What it is

The save path is how a memory observation enters durable storage. The sanctioned callers are scraper-only worker sessions (the memory miners invoked via `/extract-memory-human` and `/extract-memory-project`) — see ADR-0005. The caller supplies a `text` body plus optional `title`, `type`, `project`, and identity scope. The save path resolves project scoping (falling back to `teleclaude` when none is supplied), derives a title from the text when none is given, ensures a per-project manual session exists, and persists the observation. The persisted observation is identified by an id assigned at save and returned to the caller alongside its resolved title and project. The restriction to scraper-only callers is policy, not enforcement.

## Canonical fields

### Use cases

#### Save via CLI

```
Given a sanctioned scraper worker runs `telec memories save "<text>" [--title <t>] [--type <obs_type>] [--project <slug>]`
When the CLI builds the request body
Then it includes text; includes title only if --title was given; includes type only if --type was given; includes project only if --project was given
And asks the memory service to persist the observation
And on success prints `Saved observation #<id> — <title> (project: <project>)`
```

#### Save

```
Given a caller asks the memory service to persist an observation with a text body and optional fields
When the request is processed
Then type defaults to `discovery` when omitted
And project defaults to `teleclaude` when omitted
And title is derived from the text when omitted
And the response carries the assigned id, the resolved title, and the resolved project
```

#### Default project fallback

```
Given a save request omits project
When the memory service resolves project scoping
Then the project is set to the literal string `teleclaude`
And the observation is persisted under that project
```

#### Auto-title derivation

```
Given a save request omits title
When the memory service derives a title from the text
Then the first line after trimming surrounding whitespace is used as the source text
And the service scans for `.` first, then `!`, then `?`, returning the first matching separator whose position is greater than 0 and less than 80 (inclusive of the punctuation)
And if no scanned separator qualifies, the first 80 characters are taken verbatim
And the derived string is persisted as title
```

#### Manual-session-per-project reuse

```
Given the project has never had an observation saved under it
When the memory service saves the first observation for that project
Then a new manual session identifier is allocated for the project
And the new observation is linked to that manual session

Given the project already has a manual session
When the memory service saves another observation for that project
Then the existing manual session identifier is reused on the new observation
And no new manual session is allocated
```

#### Identity tagging at save

```
Given a save request supplies a non-null identity scope
When the memory service persists the observation
Then the observation is recorded with that identity scope
And the observation can later be retrieved by queries that filter on the same scope (see `identity-key-ownership`)
```

```
Given a save request omits identity scope
When the memory service persists the observation
Then the observation is recorded with no identity scope
And the observation can later be retrieved by any identity-scoped query plus identity-less queries (see `identity-key-ownership`)
```

### Cross-context references

- `identity` — supplies the identity scope honored at save (see `identity-key-ownership`); see `docs/project/spec/domain/identity.md`.
- `agent_runtime` — the session-start consumer does NOT save observations; it only reads them via the context-injection path. See `docs/project/spec/domain/agent_runtime.md` and `memory-context-injection`.

## Known caveats

- **No event emitted on save.** The save path produces no `memory.observation.saved` event. Consumers wanting to react to new observations must poll.
- **No author principal recorded.** Identity is recorded via the looser identity-scope mechanism (see `identity-key-ownership`); a first-class `author_principal` field is a memory-domain cutover decision.
- **Stored body field vs. domain naming.** The text body is persisted under a different field name than the memory domain spec's target naming; reconciling the two is a memory-domain decision.
- **The CLI does NOT expose an identity-scope option.** Only programmatic callers and the in-process context-injection path can supply or read identity scope. CLI-saved observations are always unscoped.
- **Integer id, not UUID.** Observations are identified by an integer id assigned at save. The memory domain spec calls for a UUID observation identifier; promoting to UUID is a cutover decision.
- **No update path.** Once persisted, an observation's fields cannot be modified; the only mutations are delete (see `observation-delete`) and search-index re-indexing.
