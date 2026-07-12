---
visibility: internal
number: 0068
date: 2026-07-12
description: Replace v1 with a separately built Rust vNext through successive authoritative vertical cuts and no compatibility bridges.
---

# vNext Replaces v1 Through Authoritative Cuts — ADR

## Context

ADR-0054 made v1 the sole destination after a substantial Rust rewrite failed
at authoritative cutover. The rewrite had built parallel services but had not
enumerated the full v1 consumer surface, continued chasing a moving v1 target,
and depended on coexistence machinery. It therefore accumulated implementation
without retiring an authoritative Python path.

Subsequent evidence changes the premise behind that decision. The running v1
platform continues to deliver value, but its process and configuration layers
produce structurally recurring repair work. In particular, checkpoint behavior
infers operational facts from shell and transcript evidence, repeats rules across
lanes that drift, and adds bookkeeping to repair false positives. The active
backlog and maintenance burden now prevent sustained progress toward the intended
platform. Continuing to ship in v1 is no longer a neutral lower-cost choice.

The durable v2 domain research, the deleted Rust implementation, and the current
documentation and review discipline provide enough evidence to define a smaller
replacement without treating the prior implementation as trusted or complete.

## Decision

Build vNext as a separately governed Rust system and replace v1 through
successive authoritative vertical cuts.

- Freeze v1 feature intake and maintain only the failures required for it to
  remain the temporary build host.
- Let vNext govern its own work from its first cut through typed verbs, durable
  facts, and independent review.
- Complete each cut only when a full journey runs authoritatively in vNext and
  the corresponding v1 path is disabled.
- Permit no shared writable state, dual writes, compatibility bridge, or ongoing
  synchronization between v1 and vNext.
- Treat the deleted Rust workspace and v2 corpus as assessed design evidence,
  not implementation lineage that bypasses review.
- Contract product scope instead of making v1 parity a completion condition.

## Consequences

- The replacement produces structural relief only through adoption; parallel
  crates and horizontal service completion no longer count as progress.
- v1 stops accumulating features, including improvements that would otherwise
  be valuable, while it serves as the temporary operational appliance.
- The first cut includes enough workflow, delivery, authorization, and session
  execution to govern one complete construction journey, increasing its initial
  scope but removing the control-plane bridge that stranded the earlier rewrite.
- Running two systems remains necessary during the cut sequence, but ownership
  is one-way and closes behind each adopted journey.
- Rust compilation and structural fitness checks enforce dependency boundaries,
  while independent review remains necessary for behavioral correctness.
- Failure to achieve the first authoritative adoption by the declared tripwire
  stops the program rather than extending an almost-finished rewrite indefinitely.
- Some v1 capabilities are retired instead of ported and can return only through
  a later journey with explicit ownership.

## Alternatives Considered

- **Continue v1 and repair it incrementally.** Rejected because the inference and
  bookkeeping machinery governs its own repair, named defect classes recur after
  fixes, and each structural correction pays the full existing process cost.
- **Build a complete replacement and cut over once.** Rejected because it delays
  all authoritative value until the highest-risk terminal event and repeats the
  prior late consumer-discovery failure.
- **Reuse v1 as vNext's workflow control plane.** Rejected because it preserves
  the exact seam being escaped and makes the old process machinery govern its
  replacement.
