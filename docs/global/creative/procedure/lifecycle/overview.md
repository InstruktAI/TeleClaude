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
the roadmap.

Governing constraints:

- **Human-in-the-loop**: three blocking gates where the machine parks and waits.
- **DB-backed state**: all state and artifacts stored in `todos.db`.
- **Artifact immutability**: the machine never modifies artifacts directly — it dispatches workers.
- **Sequential phases**: design spec precedes art, art precedes visuals.

When all three phases complete (CREATIVE_COMPLETE), creative artifacts become
preconditions for the prepare machine: `design-spec` constrains requirements,
`art/` provides visual reference, `html/` provides prototypes.

## Preconditions

- Input artifact exists in `todos.db` (`telec todo artifacts read {slug} input`).
- Work item exists in `todos.db` roadmap.

## Steps

1. Run `telec todo design [slug]` to derive the current creative phase.

2. **Design Discovery** — human and creator collaborate to produce `design-spec.md`,
   the constraint document that governs all downstream creative work. The creator
   presents reference sites, collects images the human provides (saved to
   `workspace/{slug}/input/`), and facilitates the dialogue.
   Human gate: the design spec requires explicit human confirmation before proceeding.

3. **Art Generation** — artist agent generates mood board images from the confirmed
   design spec and any reference images. Output goes to `workspace/{slug}/art/`.
   Human gate: the art requires explicit human approval before proceeding. The human
   may request iterations — the artist revises and the human reviews again.

4. **Visual Drafting** — frontender agent(s) produce self-contained HTML+CSS visual
   artifacts from the approved art and design spec. The frontender is multimodal — it
   reads the approved art images for compositional intent and uses the design spec for
   exact values. Output goes to `workspace/{slug}/html/`.
   Human gate: the visuals require explicit human approval before proceeding. For
   multi-agent bake-offs, the human selects the winning version.

5. Repeat `telec todo design [slug]` after each worker completes or human gate resolves
   until the machine returns CREATIVE_COMPLETE.

6. Proceed to `telec todo prepare [slug]` for requirements discovery.

## Outputs

- Confirmed `design-spec` artifact in `todos.db`.
- Approved images in `workspace/{slug}/art/`.
- Approved visual artifacts in `workspace/{slug}/html/`.
- Updated state in `todos.db` with creative phase completion markers.

## Recovery

- Each call is crash-safe — re-calling derives state from the filesystem and resumes.
- If blocked, the orchestrator records the blocker and surfaces it to the human.

## See Also

- ~/.teleclaude/docs/creative/design/creative-machine.md
- ~/.teleclaude/docs/creative/procedure/creative-orchestration.md
