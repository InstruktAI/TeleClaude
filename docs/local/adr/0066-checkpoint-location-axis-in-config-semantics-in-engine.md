---
visibility: public
number: 66
date: 2026-07-08
description: The checkpoint location axis (worktree | integration | main) is declared per action in project config; what each location means stays engine-owned and is not configurable.
---

# Checkpoint Location Axis in Config, Semantics in Engine — ADR

## Context

The checkpoint engine differentiates behavior by execution context, but the
differentiation is hardcoded: a single `on_main` boolean derived from branch
detection, a per-action `main_only` flag in the overlay config, and a
role-gated integrator special-case that filters the action registry to the
`main_only` set over a merge-delta file source. Three contexts — worktree,
integration, main — are compressed into a boolean and an `if`, and each new
context-specific behavior grows the engine's special-casing.

The overlay configuration (`teleclaude.yml`) is shared machinery: side projects
declare their own actions and bindings through the same schema and consume the
same engine. The question forced by growing per-context differentiation:
should context behavior be project-configurable, or platform-internal?

## Decision

Split the axis from its semantics:

- **The location axis is explicit and configurable.** Locations are an
  enumeration — `worktree | integration | main` — declared per action in the
  overlay (`locations: [main]`), replacing the boolean `main_only` flag
  (`main_only: true ≡ locations: [main]`, mechanically back-compatible).
  TeleClaude's own overlay declares its actions' locations, dogfooding the
  same surface side projects use.
- **Location semantics are engine-owned and not configurable.** What each
  location _means_ — which trigger fires there, what blocks versus advises,
  how changed files are sourced (turn-local diff, commit-obligation ledger,
  merge delta) — lives in the engine as platform process, documented in the
  checkpoint design contract, never in per-project config.

The boundary rule: **config declares what applies where; the engine owns what
each where means.**

## Consequences

- The integrator's role-gated special-case dissolves into ordinary resolution:
  actions whose locations include the current context, resolved over that
  context's file source. Engine special-casing shrinks instead of growing per
  context.
- The overlay schema gains `locations`; existing overlays keep working through
  the `main_only` mapping.
- Side projects inherit the axis through overlay projection without gaining
  the power to redefine platform process.
- Process semantics stay behind the human-ratification gate: a project config
  edit cannot silently change what integration or agent-stop enforcement
  means.

## Alternatives Considered

- **Fully configurable semantics** (triggers, blocking behavior, file sourcing
  in config). Rejected: per-project config would become a side door around
  process-change authority — any agent editing a `teleclaude.yml` could
  silently rewrite integration process without ratification.
- **Keep the boolean and role special-cases** (status quo). Rejected: each new
  context-differentiated behavior adds another hardcoded exception; the
  engine's clarity decays exactly where the platform's enforcement must be
  most legible.
