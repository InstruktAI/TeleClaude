---
description: 'Per-observation identity ownership — an opaque identity scope tagged at save time and honored at query time with inclusion-of-unscoped semantics.'
visibility: 'public'
---

# Identity Key Ownership — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

Every memory observation may carry an optional `identity_key` — an opaque string that tags the observation with an identity scope at save time. At query time, callers that supply an `identity_key` see observations tagged with that key PLUS observations with no identity scope. Callers that omit `identity_key` see all observations regardless of scope. Identity semantics live inside the `memory` bounded context: the key is recorded as-supplied with no centralized identity service, and no authorization is enforced beyond the inclusion rule. The CLI does not surface an `--identity-key` option; identity scoping is reachable only through the programmatic save/search path and through the context-injection consumer used at session start.

## Canonical fields

### Use cases

#### Tag at save

```
Given a save request supplies a non-null identity_key
When the memory service persists the observation
Then the observation is recorded with that identity scope
And the observation is later visible to any query that supplies the same key and to any query that supplies no key
```

#### Save without identity tag

```
Given a save request omits identity_key
When the memory service persists the observation
Then the observation is recorded with no identity scope
And the observation is later visible to any identity-scoped query (because of the inclusion rule below) and to any non-scoped query
```

#### Inclusion-of-unscoped on search

```
Given a search caller supplies identity_key
When the memory service builds its result set
Then the response contains observations tagged with that key AND observations with no identity scope
And observations tagged with any other key are excluded

Given a search caller omits identity_key
When the memory service builds its result set
Then no identity-related filter is applied
And the response contains observations from every identity scope
```

#### Identity scoping on context injection

```
Given the session-start consumer resolves a non-null identity_key for the session
When it requests the memory context for the project
Then the underlying observation query is identity-scoped
And the rendered context contains observations tagged with that key and observations with no identity scope only
```

```
Given the session-start consumer could not resolve an identity for the session
When it requests the memory context for the project
Then the underlying observation query is not identity-scoped
And the rendered context contains observations from every identity scope for that project
```

#### CLI never supplies identity_key

```
Given the CLI memories surface (save, search, list, timeline, delete)
When any of its verbs builds a request
Then it does NOT pass identity_key
And the resulting call is unscoped — saves record no identity scope; queries return observations from every scope
```

### Cross-context references

- `identity` — the session-start consumer resolves an identity scope for the session and hands it to the memory service as an opaque key. The `memory` context treats the value as a string and does not import the identity context's invariants beyond that. See `docs/project/spec/domain/identity.md`.

## Known caveats

- **Opaque string, no schema.** The identity scope is treated as a free-form string. There is no foreign key to an identity registry, no validation on shape, and no audit when the same key is used by different callers.
- **Identity scope is not a v2 author principal.** The memory domain spec calls for an `author_principal` field (resolved by the `identity` context) and gates updates/deletes by author-or-admin. The current scope field carries no authorization gate (see `observation-delete`) and no write-time protection — it is just a string at save. Promoting identity ownership out of `memory` into `identity` is a cutover-significant change.
- **Inclusion-of-unscoped is intentional asymmetry.** A query scoped to a key sees unscoped observations too; a query with no key sees every observation. Whether to keep this "unscoped-is-public" semantic or replace it with strict per-principal scoping is a memory-domain decision, not a feature-level one.
- **Identity scope is honored on search and on context injection only.** Bulk-fetch and timeline surfaces do not filter by identity. A caller that knows an observation id can fetch it regardless of how it was tagged at save.
- **CLI is identity-blind.** Every CLI save records no identity scope, and every CLI query returns observations from every scope. Only programmatic callers and the session-start consumer participate in identity scoping.
- **Rotation is not modeled.** If a principal's identity key is rotated, prior observations remain tagged with the old key and are not visible to queries supplying the new key. There is no migration helper.
