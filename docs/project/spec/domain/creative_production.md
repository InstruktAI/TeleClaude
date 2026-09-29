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

- **Event vocabulary:** the `domain.creative-production.*` registrations in
  `teleclaude/events/schemas/creative_production.py`.
- **Implementation roots:** `teleclaude/events/domains/creative_production/`.
- **Maintenance stance:** see `project/spec/domain/glossary`.

### Ownership boundary

- **Owns:** the meaning of its event names and payloads, their emission
  invariants, and its handlers' reactions.
- **Does not own:** the event envelope, the catalog registry, or the pipeline
  that hosts its handlers, which belong to `project/spec/domain/event-catalog`;
  or the company facts behind a company subject, which belong to config and
  identity.

<!-- planned:event-origin-and-subject -->
### Event subjects

Asset and format events are about the company whose creative work they record.
<!-- /planned:event-origin-and-subject -->

## See Also

- docs/project/spec/domain/event-catalog.md
