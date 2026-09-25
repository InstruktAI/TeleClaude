---
description: Historical reference anchor for the withdrawn local caller attestation design cited by ADR-0079.
---

# Retired Local Caller Attestation Reference — Design

## Purpose

This path preserves a resolvable reference from ADR-0079. It does not define
current caller authentication or session enrollment behavior.

## Inputs/Outputs

- **Input:** a reader following the historical reference in ADR-0079.
- **Output:** the decision record and the withdrawn proposal in Git history.

## Invariants

- No implementation or authorization decision is derived from this anchor.

## Primary flows

A reader uses ADR-0079 for the enrollment decision and consults Git history
only when the withdrawn proposal itself is needed.

## Failure modes

Treating the withdrawn proposal as a live design creates false authority.

## See Also

- docs/project/adr/0079-external-session-roots-are-enrolled-not-derived.md
