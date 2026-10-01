---
visibility: internal
description: Frozen v1 ownership anchor for the creative-production business domain hosted on the event platform — its asset and format event vocabulary and the handlers that react to it.
---

# Creative Production Domain Spec — Spec

## What it is

The v1 creative-production area is a company business domain hosted as a
domain cartridge on the event platform. It records a company's creative asset
work as events — assets moving from brief through draft, review, revision,
approval, and delivery, and format transcoding for delivery — and reacts to them
through its domain handlers.

## Canonical fields

- **Event vocabulary:** its `domain.creative-production.*` registrations in the event catalog;
  operators discover them with `telec events list`.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`.

### Ownership boundary

- **Owns:** the meaning of its event names and payloads, their emission
  invariants, and its handlers' reactions.
- **Does not own:** the event envelope, the catalog registry, or the pipeline
  that hosts its handlers, which belong to `local/projects/teleclaude/spec/domain/event-catalog`;
  or the company facts behind a company subject, which belong to config and
  identity.

<!-- planned:event-origin-and-subject -->
### Event subjects

Asset and format events are about the company whose creative work they record.
<!-- /planned:event-origin-and-subject -->

## See Also

- docs/local/spec/domain/event-catalog.md
<!-- planned:event-origin-and-subject -->
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered home its act concerned.
<!-- /planned:event-origin-and-subject -->
