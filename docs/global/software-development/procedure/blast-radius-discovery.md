---
activation_trigger: Use when you are about to edit, refactor, or explore existing code beyond a trivial one-line change — before making the edit or concluding no dependents exist.
description: Derive the blast radius of an intended code change via the codebase Blueprint before editing existing code or drawing conclusions from manual exploration.
visibility: public
---

# Blast Radius Discovery — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/spec/codebase-blueprint.md

## Goal

Derive the dependents (blast radius) of an intended change to existing code —
callers, importers, subclasses, tests — using the integrator-maintained
codebase Blueprint, before editing the code or concluding from manual
exploration that a symbol or file has no dependents.

## Preconditions

- The change touches existing code (not a brand-new, standalone file with no callers).
- The repository has a `.teleclaude/blueprint/` cache (see the codebase-blueprint spec for its location and freshness manifest).

## Steps

1. Run `telec code blueprint affected <changed-files>` for every file the
   change touches. It resolves the files' symbols and checks the baseline's
   freshness for you.

<!-- planned:code-uc-blueprint-traceability -->
   Inspect the structural dependents, shared-use-case locations, and
   reconciliation candidates separately. For use cases relevant to the intended
   change, read their defining specifications and the domain specs the code and
   specification context make relevant before deciding the change surface. Treat
   adjacent use-case identities as candidates supported by named graph edges,
   never as automatically assigned behavior.
<!-- /planned:code-uc-blueprint-traceability -->

2. Check the reported freshness. If the baseline is missing or stale (recorded
   baseline commit ≠ current `origin/main`), state the gap explicitly and fall
   back to manual exploration — never silently skip this step, and never
   generate or refresh the Blueprint yourself (generation is integrate-time
   automation only).
3. Treat the returned dependents as candidates, not an oracle. Verify each
   against the source and decide relevance; bias to over-inclusion — a missed
   dependent is a build-time surprise, an extra candidate is a discarded read.
4. Check whether a Blind spot (per the codebase-blueprint spec) applies to the
   area you're editing — dynamic dispatch, registry/string-keyed wiring,
   config-driven behavior, cross-language boundaries, reflection. Name the
   categories that apply and read those areas directly. An empty or thin
   TypeScript result is low-confidence, not evidence of no dependents.
5. For seed discovery or reachability beyond direct dependents, use `graphify
query "<terms>"`, `graphify explain "<symbol>"`, or `graphify path "<A>"
"<B>"` against the same baseline.
6. Ground your change surface — or your plan, or your understanding of the
   codebase — in the verified candidate set from steps 3–4.

## Outputs

- A verified dependent set, or an explicit stated gap when the baseline is
  stale, missing, or unsupported for the area — grounding the change surface.

## Recovery

- If the CLI reports the baseline stale or missing, do not attempt to
  regenerate it. State the gap and fall back to manual `grep`/exploration,
  noting the fallback explicitly rather than silently proceeding as if no
  dependents exist.

## Discipline

Blast-radius discovery gets skipped for two reasons: the agent doesn't know
this procedure exists, or the agent treats a thin/empty result as proof of no
dependents rather than a blind-spot signal. Both produce the same failure — a
change lands, breaks an unseen caller, and nobody grepped for it. Run this
before concluding a file is unreferenced or safe to change; an empty result
from a Blind-spot area is not evidence of safety.
