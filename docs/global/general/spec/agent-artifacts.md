---
description: 'Minimal schema used for agent artifacts (skills).'
visibility: 'public'
---

# Agent Artifacts — Spec

## What it is

Defines the normalized artifact format we author and how it maps to each
supported agent runtime. This doc is the concrete reference for what exists,
what is emitted, and where those outputs land. Skills are the one artifact
kind; what an agent is assigned at session start is a procedure
(`general/spec/snippet-authoring-schema`, entry declarations), never an
artifact.

## Canonical fields

- **Skills**:
  - Frontmatter: required `name` and `description`
  - Identity: `name` must equal the containing folder in every skill package
  - Body: pass-through; never graded against TeleClaude's artifact taxonomy

## Allowed values

- `description`: short, imperative summary.
- `name`: identifier used for artifact lookup. A skill's folder is its runtime
  identity, so its required source `name` must equal that folder.

### Skills

The `SKILL.md` body and every supporting Markdown resource retain their upstream
structure and are not checked against any section taxonomy. The universal `name`,
`description`, and folder-identity contract applies to the entrypoint.

## Known caveats

- Skill packages may carry upstream fields in addition to the universal identity
  fields.
- Skill bodies are pass-through in both scopes. Supporting Markdown is always
  opaque to taxonomy validation. Every package uses the same rendering and
  target-transformation pipeline.
- Scope is conveyed by location, mirroring the global and local halves of `docs/`:
  - **Global scope**: `TeleClaude/agents/global/skills/*/SKILL.md` from the mother alone
  - **Local scope**: `<project>/agents/local/skills/*/SKILL.md`
  - `.agents/` is a delivery location and is never read as a source
- Required reads in source docs are **inlined** in generated outputs; `@` references
  are transformed into inline content and do not appear in emitted files. A
  `## Required reads` ref is **hoisted** to the top of the compiled artifact. To
  land a snippet at a specific point in the body instead — adjacent to the step
  that needs it — place an `@include` directive (`@include: <path>` inside an HTML
  comment) at that point rather than filing the ref under Required reads.

### Runtime support matrix

Global skills compose to the catalog and reach no runtime home. What a runtime
receives natively is its entrypoint master and the tier-local skills of the root
it runs in; the mother's deployment contract owns the per-runtime locations.

- **Claude Code**: entrypoint master, tier-local skills
- **Codex CLI**: entrypoint master, tier-local skills
- **Gemini CLI**: entrypoint master, tier-local skills
