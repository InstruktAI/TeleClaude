---
visibility: internal
description: Frozen v1 pointer to the executable event catalog and feature contracts that consume it.
---

# Event Catalog — Spec

## What it is

The v1 event catalog is executable source, not a second handwritten registry.
Event schemas, metadata, and delivery behavior are read from the implementation
and from the feature specs that bind observable behavior.

## Canonical fields

- **Schema authority:** `teleclaude/events/schemas/` and
  `teleclaude/events/catalog.py`.
- **Operator discovery:** `telec events list`.
- **Delivery implementation:** `teleclaude/events/`.
- **Maintenance stance:** see `project/spec/domain/glossary`. No replacement event model is
  authored here.

### Ownership boundary

The catalog owns registry shape, discovery metadata, and delivery-envelope
contracts. The bounded context that produces an event owns its semantic name,
payload meaning, and emission invariant; consuming contexts own their local
reaction. Catalog registration does not transfer either responsibility.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
