---
visibility: internal
description: vNext Rust workspace layout, source-size budgets, dependency enforcement, scaffolding, and verification constitution.
---

# vNext Code Organization — Design

## Required reads

@docs/project/design/architecture-vnext/overview.md

## Purpose

Make architecture visible in paths and cheap for agents to load. The layout
prevents agents from inventing structures, hides no dependency direction, and
uses mechanical limits before files or crates exceed reliable comprehension.

## Inputs/Outputs

**Inputs:** bounded-context ownership, application journeys, adapters,
binaries, Rust compilation boundaries, and observed agent degradation in
large files and broad crates.

**Outputs:** a fixed workspace map, source budgets, split triggers, a sanctioned
scaffolder, and CI checks that reject structural drift.

## Invariants

- Paths communicate layer, context, and dependency direction without requiring
  an agent to infer them from imports.
- New contexts and crates are created only through the workspace scaffolder.
  Agents do not choose novel top-level or context-local layouts.
- Every context uses `core` and optional `postgres` crates in one context
  folder. A third crate requires a distinct dependency boundary and consumer.
- Core ports are domain verbs, never generic CRUD or repository traits.
- There are no accumulating `utils`, `helpers`, `common`, generic `models`, or
  generic `events` dumping grounds. Small cohesive `models.rs` files are valid.
- `lib.rs` files are small facades. Implementation lives in responsibility-
  named modules.
- No future context gets empty crate scaffolding before its authoritative cut.
- Generated and declarative artifacts are indexed separately from hand-authored
  source and cannot hide executable logic.

## Primary flows

### Workspace layout

```text
crates/
  foundation/
    kernel/
    storage/
    observability/
  domains/
    identity/{core,postgres}/
    access/{core,postgres}/
    organization/{core,postgres}/
    workspace/{core,postgres}/
    workflow/{core,postgres}/
    delivery/{core,postgres}/
    sessions/{core,postgres}/
  adapters/
    uds/
    tmux-codex/
    git/
  applications/
    work-control/
    agent-dispatch/
    delivery-control/
  binaries/
    telec/
    telec-hook/
    telec-daemon/
    telec-executor/
xtask/
```

Only cut-1 crates exist initially. Later context folders enter through their
cut's contract and scaffolding change.

Cut 1 contains 28 packages: three foundation crates, fourteen context crates,
three adapters, three application crates, four binaries, and `xtask`. Package
names are globally unique, including the context and layer, such as
`telec-workflow-core` and `telec-workflow-postgres`.

### Source budgets

| Unit                      |      Target | Mandatory review |    Hard cap |
| ------------------------- | ----------: | ---------------: | ----------: |
| Hand-authored source file |   600 lines |        900 lines | 1,200 lines |
| Rust crate                | 2,500 lines |      3,500 lines | 5,000 lines |
| Context component         |           - |      8,000 lines |           - |

Crossing a review threshold requires a decomposition decision in the same
change. The reviewer either identifies a cohesive split or records why the
unit remains singular. Hard-cap exceptions require an explicit architecture
change; they are not lint suppressions.

Generated migrations, snapshots, lockfiles, and derived schemas do not count
against hand-authored source limits. CI reports their size and provenance and
rejects executable source classified as generated.

### Split triggers

An application crate splits when actor/action family, transaction owner,
runtime topology, or change cadence diverges. A context splits into subdomains
when it contains independently changing language, aggregates, and facts. File
size is a backstop, not the only reason to split.

The scaffolder creates manifests, dependency declarations, README module maps,
schema ownership metadata, and test locations from one approved template.
Every crate README states responsibility, public API, allowed dependencies,
and module map.

### Fitness checks

CI enforces:

- allowed Cargo dependency edges and forbidden infrastructure dependencies;
- one schema and migration root per persistent context;
- folder registry and scaffolder conformity;
- source-size budgets and generated-source classification;
- `cargo fmt`, `clippy -D warnings`, locked dependency checks, and audits;
- secret scanning and unsafe-code policy;
- public API and domain-event compatibility;
- real-Postgres functional tests and end-to-end CLI journeys;
- database grants that reject every foreign-schema runtime query;
- the hostile execution suite against the exact Codex launch profile.

Tests bind domain invariants, public contracts, and user journeys. Mock
interaction tests, wiring echoes, and tests that duplicate compiler guarantees
do not earn a place. Core decision functions use direct deterministic tests;
Postgres implementations use isolated real database schemas.

### Parallel work

Cut 1 permits at most three builder agents and one integrator. Module ownership
is explicit per work item. One agent changes one context component or journey
at a time unless the plan names the cross-context orchestration.

Reviewed package branches merge into one wave integration branch. A wave
reaches `main` only when its complete journey is green; individual crates do
not land on `main` as horizontal progress. Foundation wave W0 is the sole
exception; it establishes the checks that enforce every later wave.

## Failure modes

- The grouped workspace exists visually but Cargo edges permit layer bypasses.
- A context becomes one large crate because files remain individually small.
- Trait layers duplicate every query without protecting an architectural seam.
- Application crates become process-shaped god modules such as `app-control`.
- Agents create alternate folder patterns because the scaffolder lacks a case.
- Tests assert mocks and call ordering while domain invariants remain uncovered.
- Generated-code exemptions become a way to evade source limits.

## See Also

- docs/project/adr/0068-vnext-replaces-v1-through-authoritative-cuts.md
- docs/project/design/architecture-vnext/runtime-and-facts.md
- docs/project/design/architecture-vnext/cutover-program.md
