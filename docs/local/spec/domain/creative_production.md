---
visibility: internal
description: Frozen v1 ownership anchor for the creative-production business domain whose asset and format event vocabulary the event platform's catalog hosts.
---

# Creative Production Domain Spec — Spec

## What it is

The v1 creative-production area is a company business domain whose event
vocabulary the event platform's catalog hosts. It records a company's creative
asset work as events — assets moving from brief through draft, review,
revision, approval, and delivery, and format transcoding for delivery.

## Canonical fields

- **Event vocabulary:** its `domain.creative-production.*` registrations in the event catalog;
  operators discover them with `telec events list`.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`.

### Ownership boundary

- **Owns:** the meaning of its event names and payloads, and their emission
  invariants.
- **Does not own:** the event envelope or the catalog registry, which belong to
  `local/projects/teleclaude/spec/domain/event-catalog`; or the company facts
  behind a company subject, which belong to config and identity.

### Event subjects

Asset and format events are about the company whose creative work they record.

## See Also

- docs/local/spec/domain/event-catalog.md
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered home its act concerned.
