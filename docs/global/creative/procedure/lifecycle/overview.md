---
id: 'creative/procedure/lifecycle/overview'
type: 'procedure'
domain: 'creative'
scope: 'global'
description: 'Creative lifecycle overview. Optional pre-stage: design spec, art generation, visual artifacts — feeding into the software development lifecycle.'
---

# Creative Lifecycle Overview — Procedure

## Goal

Transform human visual intent into confirmed design specifications, approved art, and
approved visual artifacts. The creative lifecycle is an optional pre-stage that runs
before the software development lifecycle (prepare, work, integrate). Its output becomes
a precondition for requirements discovery.

Not every todo requires creative work. The creative stage activates only when the todo
involves visual or creative work — explicitly stated in `input.md` or flagged in
`roadmap.yaml`.

The lifecycle has three sequential phases, each with a human gate:

1. **Design Discovery** — human and creator collaborate to produce `design-spec.md`.
   Human gate: explicit confirmation required.

2. **Art Generation** — artist agent generates mood board images from the confirmed
   design spec and reference images. Output to `todos/{slug}/art/`.
   Human gate: explicit approval required (iterations allowed).

3. **Visual Drafting** — frontender agent(s) produce HTML+CSS visual artifacts from
   approved art and design spec. Output to `todos/{slug}/html/`.
   Human gate: explicit approval required (bake-off selection for multi-agent).

When all three phases complete (CREATIVE_COMPLETE), creative artifacts become
preconditions for the prepare machine: `design-spec.md` constrains requirements,
`art/` provides visual reference, `html/` provides prototypes.

Work state lives in `todos/{slug}/state.yaml` under the `creative` section. All state
is derived from filesystem artifacts — each call is crash-safe.

## Preconditions

- `todos/{slug}/input.md` exists with human thinking.
- Work item exists in `todos/roadmap.yaml`.

## Steps

1. Run `telec todo create [slug]` to derive the current creative phase.
2. Follow the returned instruction (facilitate design discovery, dispatch artist,
   dispatch frontender, or park at human gate).
3. Repeat until the machine returns CREATIVE_COMPLETE.
4. Proceed to `telec todo prepare [slug]` for requirements discovery.

## Outputs

- Confirmed `todos/{slug}/design-spec.md`.
- Approved images in `todos/{slug}/art/`.
- Approved visual artifacts in `todos/{slug}/html/`.
- Updated `state.yaml` with creative phase completion markers.

## Recovery

- Each call is crash-safe — re-calling derives state from the filesystem and resumes.
- If blocked, the orchestrator records the blocker and surfaces it to the human.
