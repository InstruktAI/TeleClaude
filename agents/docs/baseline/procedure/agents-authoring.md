# AGENTS.md Authoring

Required reads

@~/.teleclaude/docs/baseline/procedure/snippet-authoring-sequence.md
@~/.teleclaude/docs/baseline/policy/referencing-doc-snippets.md

## Goal

Provide a consistent, minimal `AGENTS.md` that bootstraps required reading for AI agents.

## Preconditions

- Project has a `docs/` folder with taxonomy subfolders.
- Project baseline index exists at `docs/baseline/index.md`.

## Steps

1. Start `AGENTS.md` with the two required baseline lines:
   - `@~/.teleclaude/docs/baseline/index.md`
   - `@docs/baseline/index.md`
2. Keep `AGENTS.md` minimal; avoid duplicating docs content.
3. Add short project notes only when required for immediate safety or navigation.
4. Ensure any additional required reads are placed in the project baseline index,
   not directly in `AGENTS.md`.

## Outputs

- `AGENTS.md` includes the two required baseline references.
- Project baseline index lists all project-specific required reads.

## Recovery

- If `AGENTS.md` contains extra required reads, move them into `docs/baseline/index.md`.
- If baseline index is missing, create it and keep it as the single source of project required reads.
