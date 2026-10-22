---
description: 'Per-observation identity ownership — an opaque identity scope tagged at save time and honored at query time with inclusion-of-unscoped semantics.'
visibility: 'public'
---

# Identity Key Ownership — Spec

## What it is

Every memory observation may carry an optional `identity_key` — an opaque string that tags the observation with an identity scope at save time. At query time, callers that supply an `identity_key` see observations tagged with that key PLUS observations with no identity scope. Callers that omit `identity_key` see every observation their reach admits, regardless of scope. Every read that serves a caller — search, listing, and timeline — returns only observations the caller's reach admits by the subject each observation records (`local/projects/teleclaude/spec/feature/identity/data-visibility`), applied before the result limit; `identity_key` only narrows within that. The key is memory's own narrowing, recorded as-supplied; it grants nothing. The CLI does not surface an `--identity-key` option; identity scoping is reachable only through the programmatic save/search path and through the context-injection consumer used at session start.

## Canonical fields

### Conversation curation

Worker curation explicitly selects a canonical identity and optional desk under
`local/projects/teleclaude/spec/feature/memory/memory-curation`. Automatic
personal and visitor context uses that strictly resolved scope; unresolved
legacy observations remain retained without automatic attribution. The generic
programmatic and administrative surfaces retain their existing reach contracts.
Source sessions and extraction identities carry provenance and progress.

### Use cases

#### UC-IKO1: An agent retrieves memory for a person

```
Scenario: Retrieve memories in the person's identity context
  Given an agent acts for person X
  When it searches memory in X's identity context
  Then results include observations scoped to X and observations with no identity scope
  And observations scoped to other identities are excluded
```

### Cross-context references

- `identity` — the session-start consumer resolves an identity scope for the session and hands it to the memory service as an opaque key. The `memory` context treats the value as a string and does not import the identity context's invariants beyond that. See `docs/local/spec/domain/identity.md`.

## Known caveats

- **Opaque string, no schema.** The identity scope is treated as a free-form string. There is no foreign key to an identity registry, no validation on shape, and no audit when the same key is used by different callers.
- **Identity scope is not a v2 author principal.** The memory domain spec calls for an `author_principal` field (resolved by the `identity` context) and gates updates/deletes by author-or-admin. The current scope field carries no authorization gate (see `observation-delete`) and no write-time protection — it is just a string at save. Promoting identity ownership out of `memory` into `identity` is a cutover-significant change.
- **Inclusion-of-unscoped is intentional asymmetry.** A query scoped to a key sees unscoped observations too; a query with no key sees every observation. Whether to keep this "unscoped-is-public" semantic or replace it with strict per-principal scoping is a memory-domain decision, not a feature-level one.
- **Identity scope is honored on search and on context injection only.** Bulk-fetch and timeline surfaces do not filter by identity. A caller that knows an observation id can fetch it regardless of how it was tagged at save.

- **CLI is identity-blind outside curation.** Every CLI save records no identity scope, and every CLI query returns observations from every scope. Only programmatic callers, the session-start consumer, and curation — whose operations name a resolved identity and optional desk (`local/projects/teleclaude/spec/feature/memory/memory-curation`) — participate in identity scoping.

- **Rotation is not modeled.** If a principal's identity key is rotated, prior observations remain tagged with the old key and are not visible to queries supplying the new key. There is no migration helper.
