---
visibility: public
number: 0094
date: 2026-09-20
description: Documentation and agent-artifact publication activates only from validated recorded commits and recovers by replaying their maintenance action.
---

# Publication Activates From Recorded Commits — ADR

## Context

ADR-0088 moved documentation and agent-artifact deployment from filesystem saves to the commit boundary, but retained a directly invocable deploy command for bootstrap and recovery. That command could still publish the caller's current working tree, so deployed state did not necessarily identify a validated commit even after the ambient watcher was removed.

The remaining fork was whether explicit callers should retain that working-tree publication escape hatch, or whether every publication should identify the validated committed state that authorized it. Initial setup and recovery still need activation paths, but neither requires treating an arbitrary working tree as authoritative: setup can activate a clean committed head, and recovery can replay the maintenance action recorded for the failed commit range.

## Decision

Documentation and agent-artifact publication activates only from validated recorded commits. Canonical commit and merge maintenance publish the committed range they carry. Initial setup may activate an already-committed clean head after blocking validation. Recovery replays the recorded maintenance action for its original commit range. No public command publishes the caller's current working tree.

## Consequences

- Every deployed generation is attributable to a validated commit and publication action.
- Saving or editing source has no deployment effect until that source is committed.
- A failed publication can leave deployed state behind repository state until its recorded maintenance action succeeds; the commit itself remains standing.
- Recovery is narrower and more reproducible because it replays identified committed input instead of whatever happens to be in the working tree later.
- Initial activation requires a clean committed head and fails rather than publishing uncommitted setup state.
- The former deploy command cannot serve as an ad hoc preview mechanism. Any future preview capability must be explicitly non-deploying and isolated from runtime outputs.
- Publication keeps its host serialization and atomic replacement guarantees; constraining source authority does not remove concurrent committed activations.

## Alternatives Considered

- Keep direct working-tree publication for bootstrap and recovery. Rejected because it preserves a path by which runtime state cannot be traced to the commit gate that validated it.
- Keep direct publication but require a clean tree. Rejected because it creates a second activation contract alongside recorded maintenance and leaves recovery without the original failed range as its authority.
- Re-run publication against the latest head after a failure. Rejected because later commits may have changed the source, turning recovery into an unrecorded replacement rather than a replay of the failed action.
