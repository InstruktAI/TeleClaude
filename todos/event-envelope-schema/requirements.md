# Requirements: event-envelope-schema

## Goal

Formalize the five-layer event envelope as the canonical wire format for TeleClaude's
event platform and future mesh communication. The `EventEnvelope` model already exists
in `teleclaude_events/envelope.py` — this work hardens it into a versioned, self-describing
schema with a complete core taxonomy and an expansion joint for organic evolution.

## Scope

### In scope

1. **Core event taxonomy** — Register the root-level event families from `input.md`
   (`node.*`, `deployment.*`, `content.*`, `notification.*`, `schema.*`) as catalog
   entries in `teleclaude_events/schemas/`. The `system.*` and
   `domain.software-development.*` families already exist and stay as-is.

2. **Expansion joint** — Enable `extra="allow"` on `EventEnvelope` so additional
   properties pass through validation, serialization, and deserialization without loss.
   This is the mechanism for organic schema evolution described in `input.md`.

3. **Schema versioning constant** — Replace the hardcoded `version: int = 1` default
   with a constant derived from the package's major version. The envelope's `version`
   field tracks the schema generation, not the full semver.

4. **JSON Schema export** — Add a utility that produces a JSON Schema document from the
   Pydantic model. This enables external mesh participants and tooling to validate
   envelopes without importing Python code.

5. **Round-trip integrity** — Ensure extra fields survive the Redis stream
   `to_stream_dict` → `from_stream_dict` round-trip and the JSON Schema validates
   real envelopes from the catalog.

6. **Event vocabulary spec update** — Update `docs/project/spec/event-vocabulary.md`
   to reference the core taxonomy families and the expansion joint mechanism.

### Out of scope

- Mesh transport implementation (that's `mesh-architecture`).
- Trust evaluation of envelope fields (that's `mesh-trust-model`).
- Domain pipeline cartridges beyond the existing system and software-development schemas.
- Payload schema validation per event type (future work, not needed for wire format).
- Migration logic for version negotiation between nodes (future mesh concern).
- Changes to the existing `EventLevel`, `EventVisibility`, or `ActionDescriptor` models.

## Success Criteria

- [ ] All root-level event families from `input.md` are registered in the catalog
      with appropriate defaults (level, domain, visibility, lifecycle).
- [ ] `EventEnvelope(event="x.y", ..., custom_field="val")` round-trips through
      `to_stream_dict()` → `from_stream_dict()` preserving `custom_field`.
- [ ] `SCHEMA_VERSION` constant exists and is used as the default for `version`.
- [ ] `EventEnvelope.model_json_schema()` produces a valid JSON Schema document.
- [ ] A helper function exports the schema to a file for external consumption.
- [ ] Existing tests continue to pass — no regression in current event processing.
- [ ] `docs/project/spec/event-vocabulary.md` documents the core taxonomy families.

## Constraints

- The envelope model is consumed by `teleclaude_events/processor.py`,
  `teleclaude_events/producer.py`, cartridges, and delivery adapters. Changes must
  be backward-compatible with all existing consumers.
- Redis stream serialization must remain a flat `dict[str, str]` — extra fields are
  JSON-encoded into a single `_extra` key to preserve the flat constraint.
- No new external dependencies. Pydantic's built-in JSON Schema generation is sufficient.

## Risks

- Extra field round-trip through Redis requires a serialization strategy for the `_extra`
  bucket. Mitigation: use a single JSON-encoded `_extra` key in the stream dict.
- Naming reconciliation between input.md's flat families (`node.*`) and the existing
  `domain.*` prefix pattern. Mitigation: new families use the flat pattern from input.md;
  existing `domain.software-development.*` stays as-is. Both patterns coexist — the
  `domain.` prefix is a convention for domain-scoped events, not a requirement.
