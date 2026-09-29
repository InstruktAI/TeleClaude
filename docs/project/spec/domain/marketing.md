---
visibility: internal
description: Frozen v1 ownership anchor for the marketing business domain hosted on the event platform — its content, campaign, and feed event vocabulary and the handlers that react to it.
---

# Marketing Domain Spec — Spec

## What it is

The v1 marketing area is a company business domain hosted as a domain cartridge
on the event platform. It records a company's marketing work as events —
content moving from brief to publication and performance, campaigns from launch
to report, and feed items bridged from the signal pipeline — and reacts to them
through its domain handlers.

## Canonical fields

- **Event vocabulary:** the `domain.marketing.*` registrations in
  `teleclaude/events/schemas/marketing.py`.
- **Implementation roots:** `teleclaude/events/domains/marketing/`.
- **Maintenance stance:** see `project/spec/domain/glossary`.

### Ownership boundary

- **Owns:** the meaning of its event names and payloads, their emission
  invariants, and its handlers' reactions.
- **Does not own:** the event envelope, the catalog registry, or the pipeline
  that hosts its handlers, which belong to `project/spec/domain/event-catalog`;
  the signal pipeline whose output its feed bridge consumes; or the company
  facts behind a company subject, which belong to config and identity.

<!-- planned:event-origin-and-subject -->
### Event subjects

- Content and campaign events are about the company whose marketing they
  record.
- A feed event bridged from a signal event states that signal event's subject.
<!-- /planned:event-origin-and-subject -->

## See Also

- docs/project/spec/domain/event-catalog.md
