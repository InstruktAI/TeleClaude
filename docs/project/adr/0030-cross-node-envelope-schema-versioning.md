---
adr_status: 'accepted'
date: '2026-06-11'
description: 'Cross-node event envelopes carry a schema_version stamp (current shape is version 1) and consumers read them as tolerant readers, so a fleet of differently-versioned nodes interoperates across additive changes. An absent stamp decodes as version 1.'
number: '30'
visibility: 'public'
---

# ADR-0030: Cross-Node Envelope Schema Versioning — ADR

## Context

A fleet can contain nodes upgraded at different times. The envelopes that cross
node boundaries — the v2 Rust `EventEnvelope` and the v1 `cluster.*`
`ClusterEnvelope` — need a compatibility rule that lets a newer producer add
fields without breaking an older consumer, and lets a newer consumer read
envelopes emitted before any version stamp existed.

## Decision

Every cross-node envelope carries a `schema_version` stamp. The current envelope
shape is version `1`.

Consumers are tolerant readers:

- An absent `schema_version` decodes as version `1`, preserving compatibility
  with envelopes emitted before the stamp existed.
- Unknown added fields are ignored by consumers that do not understand them.
- A present but malformed known field remains malformed and fails at the decode
  boundary.
- A consumer that rejects an otherwise valid cross-node envelope solely because
  of an unknown field is defective.

A future non-additive change to a cross-node envelope bumps the schema version
and carries an explicit migration strategy.

## Consequences

Differently-versioned nodes tolerate additive envelope evolution: a newer node
emits a stamped envelope and an older tolerant reader keeps processing the fields
it understands; a newer node reads an unstamped envelope without treating absence
as corruption.

The rule constrains envelope and cross-node payload decoders: they must not opt
into unknown-field rejection. Strict unknown-field validation remains correct for
HTTP request and query models, which are not cross-node envelopes.

The stamp is a decode-level compatibility floor only. It does not by itself
provide capability negotiation, feature gating, or semantic upcasting.

## Alternatives Considered

- **Leave envelopes unstamped, rely on informal additive discipline.** Rejected:
  consumers would have no durable way to reason about envelope shape and would
  have to infer baseline state from absence alone.
- **Reject unknown fields to keep schemas strict.** Rejected for cross-node
  envelopes: strict rejection breaks rolling upgrades. Strict validation stays
  correct for request and query boundaries.
- **Build a general upcaster framework now.** Rejected: the present need is
  additive-envelope tolerance; a general upcaster adds machinery before any
  non-additive migration exists.
