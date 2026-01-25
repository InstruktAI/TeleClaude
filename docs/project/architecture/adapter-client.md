---
description:
  AdapterClient centralizes adapter lifecycle, UI/transport routing, and
  cross-computer requests.
id: teleclaude/architecture/adapter-client
scope: project
type: architecture
---

# Adapter Client — Architecture

## Purpose

- @docs/concept/adapter-types

- Own adapter lifecycle and fan-out delivery to adapters.

- Inputs: commands and events from core logic that need to reach adapters.
- Outputs: fan-out delivery to adapters.

- Fans out output updates to the correct adapters based on last input origin and configuration.
- Ensures UI channel metadata before first delivery to a non-origin adapter.
- Applies UI cleanup hooks and observer notifications around user input and AI output.

- Only successfully started adapters are registered.
- Delivery runs in parallel lanes so one adapter cannot block another.

- Adapter failures are isolated per lane and logged.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
