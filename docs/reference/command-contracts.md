---
id: teleclaude/reference/command-contracts
type: reference
scope: project
description: Command contract highlights for session creation, messaging, and agent control.
---

## What it is

- Command contract highlights for session creation, messaging, and agent control.

## Canonical fields

- Commands require explicit session identifiers and payloads.
- Command intent must be explicit and stable across interfaces.
- Enumerated intent values are treated as strict contracts.

## Allowed values

- Enumerated intent fields must match the declared command contract.

## Known caveats

- Commands are rejected when the target session is missing or closed.
