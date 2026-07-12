---
visibility: internal
description: Historical reference anchor for the retired v2 data-upcasting design named by an immutable ADR.
---

# Retired Data Upcasting Reference — Design

## Purpose

This path preserves a resolvable reference from the immutable ADR timeline. It
does not define current v1 behavior or replacement architecture.

## Inputs/Outputs

- **Input:** a reader following the historical reference in ADR-0025.
- **Output:** the authority boundary in ADR-0069 and the original design in Git
  history.

## Invariants

- No implementation or migration work is derived from this anchor.
- No pending delivery owns this anchor.
- TeleClaudeNext is the only authority for replacement data evolution.

## Primary flows

A reader uses Git history when the retired proposal itself is relevant and
uses ADR-0069 to locate the current replacement authority.

## Failure modes

Treating this reference anchor as a live design creates a second architecture
authority and is invalid.

## See Also

- docs/project/adr/0025-two-layer-migration-model.md
- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
