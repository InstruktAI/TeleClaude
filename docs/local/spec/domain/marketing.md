---
visibility: internal
description: Frozen v1 ownership anchor for the marketing business domain whose content, campaign, and feed event vocabulary the event platform's catalog hosts.
---

# Marketing Domain Spec — Spec

## What it is

The v1 marketing area is a company business domain whose event vocabulary the
event platform's catalog hosts. It records a company's marketing work as
events — content moving from brief to publication and performance, campaigns
from launch to report, and feed items bridged from the signal pipeline.

## Canonical fields

- **Event vocabulary:** its `domain.marketing.*` registrations in the event catalog;
  operators discover them with `telec events list`.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`.

### Ownership boundary

- **Owns:** the meaning of its event names and payloads, and their emission
  invariants.
- **Does not own:** the event envelope or the catalog registry, which belong to
  `local/projects/teleclaude/spec/domain/event-catalog`; the signal pipeline
  its feed items are bridged from; or the company facts behind a company
  subject, which belong to config and identity.

### Event subjects

- Content and campaign events are about the company whose marketing they
  record.
- A feed event bridged from a signal event states that signal event's subject.

## See Also

- docs/local/spec/domain/event-catalog.md
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered home its act concerned.
