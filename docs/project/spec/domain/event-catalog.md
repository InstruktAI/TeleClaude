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
- **Maintenance boundary:** events change only as part of approved v1 P0 work;
  no replacement event model is authored here.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
