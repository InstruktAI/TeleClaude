---
visibility: public
number: 0069
date: 2026-07-12
description: The TeleClaudeNext repository is the sole authority for vNext architecture, program state, reviews, and implementation.
---

# vNext Authority Lives in a Separate Repository — ADR

## Context

ADR-0068 chose a separately governed Rust replacement and prohibited v1 from
acting as its workflow control plane. The reviewed vNext corpus initially lived
in the v1 repository so the architecture conversation could use the existing
documentation and review surfaces. After a separate repository acquired a
reviewed seed, retaining another active copy in v1 would create two apparent
authorities and require manual synchronization.

## Decision

The repository at `/Users/Morriz/Workspace/InstruktAI/TeleClaudeNext`, beginning
with seed commit `579c9480efa3e0f4f61e87258d5b6c6998ff69e1`, is the sole
authority for vNext architecture, program state, review evidence, and
implementation. v1 retains this decision pointer and its own current-behavior
contracts only. No vNext design mirror, writable bridge, or synchronized
program state remains in v1.

## Consequences

- Agents working on vNext enter the separate repository and cannot mistake v1
  workflow or documentation state for vNext authority.
- v1 Git history retains the architecture discussion and original reviewed
  corpus without publishing a duplicate current copy.
- The separate repository must preserve its own review evidence, backups, and
  operating instructions from its seed onward.
- Cross-repository discovery depends on this pointer until v1 is retired.

## Alternatives Considered

- **Keep v1 canonical and copy changes into vNext.** Rejected because the
  replacement would remain governed by the platform it is replacing.
- **Maintain synchronized design copies.** Rejected because synchronization is
  a second authority mechanism and can drift without either repository failing.
- **Keep vNext inside the v1 repository.** Rejected because v1 process hooks,
  workflow state, and repository-wide structural rules would continue to
  govern the replacement.
