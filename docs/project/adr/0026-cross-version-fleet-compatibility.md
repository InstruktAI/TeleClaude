---
adr_status: accepted
date: '2026-06-11'
description: Cross-node event envelopes carry schema versions and consumers read them
  tolerantly so mixed-version fleets can interoperate across additive changes.
number: '26'
visibility: public
---

# Cross Version Fleet Compatibility — ADR

## Context

TeleClaude fleets can contain nodes upgraded at different times. Cross-node
events therefore need a compatibility rule that lets newer producers add
envelope fields without breaking older consumers, and lets newer consumers read
baseline envelopes emitted before the version stamp existed.

The v2 Rust `EventEnvelope` and the v1 `cluster.*` `ClusterEnvelope` are the two
cross-node envelopes in scope for this foundation slice. The Python stream
`EventEnvelope` is already versioned and already allows extra fields. Capability
gating, feature registries, and generalized upcasters are separate work.

## Decision

Every cross-node envelope carries a schema-version stamp. The current envelope
shape is version `1`.

Consumers are tolerant readers:

- An absent `schema_version` decodes as version `1`, preserving compatibility
  with baseline envelopes emitted before the stamp existed.
- Unknown added fields are ignored by consumers that do not understand them.
- A present malformed known field remains malformed and must fail at the
  decode boundary.
- A consumer that rejects an otherwise valid cross-node envelope because of an
  unknown field is defective.

This decision applies to the v2 Rust `EventEnvelope` and the v1 `cluster.*`
`ClusterEnvelope`. Future non-additive envelope changes must bump the schema
version and provide an explicit migration strategy.

## Consequences

Mixed-version fleets can tolerate additive envelope evolution: newer nodes can
emit stamped envelopes and older tolerant readers continue processing the
fields they understand. Newer nodes can also read unstamped baseline envelopes
without treating absence as corruption.

The rule constrains future event-consumer implementations. Envelope and
cross-node event payload decoders must not opt into unknown-field rejection
unless they are validating a non-event ingress boundary. Strict validation
remains appropriate for HTTP request and query models, which are not governed by
the cross-node tolerant-reader rule.

The version stamp is only a foundation. It does not by itself provide
capability negotiation, feature gating, or semantic upcasting; those remain
explicit follow-up concerns.

## Alternatives Considered

- **Leave envelopes unstamped and rely on informal additive discipline.**
  Rejected because consumers would have no durable way to reason about envelope
  shape, and future compatibility work would have to infer baseline state from
  absence alone.
- **Build the full upcaster framework immediately.** Rejected for this slice
  because the immediate compatibility need is additive-envelope tolerance; a
  generalized upcaster would add more machinery before a non-additive migration
  exists.
- **Reject unknown fields to keep schemas strict.** Rejected for cross-node
  events because strict unknown-field rejection breaks rolling upgrades. Strict
  ingress validation remains correct for request/query boundaries outside the
  event mesh.
