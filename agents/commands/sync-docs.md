---
description: Generate or refresh atomic docs from the codebase for AI context selection.
argument-hint: "[scope|--reset]"
---

# Synchronize Docs

Create or update `docs/` to reflect the actual architecture and behavior of the codebase. Docs are the single source of truth for AI context selection.

## Scope

Scope: "$ARGUMENTS"

- Scope: optional focus area (path, feature, or component). If omitted, cover the whole repo.
- If scope includes `--reset`, rebuild docs from scratch (destructive). Use only after major refactors.

## Snippet Authoring Reference

@docs/guide/snippet-authoring.md

Read the snippet indexes to learn what exists:

- `agents/docs/index.yaml`
- `docs/index.yaml`

## Directory Convention

- `docs/` — output only (do NOT read as input)
- Use other documentation as input: `README.md`, `AGENTS.md`, `docs/**/*.md` except `docs/` and `docs-3rd/`
- `docs-3rd/` is external research; never use it as input

## State-Based Workflow

### State A: No `docs/` (legacy repo)

- **Ignore existing docs** (none yet).
- Read legacy docs (`docs/**/*.md` excluding `docs/` and `docs-3rd/`).
- Read codebase using targeted scanning (entrypoints, core modules, adapters, tests).
- Build docs from **code + legacy docs**.
- Create an initial sync commit: `docs(docs): initial sync`.

### State B: `docs/` exists

- **Do not trust existing docs**. This is the most important case.
- Start by auditing code + legacy docs; treat existing docs as output only.
- If existing docs are incomplete or skewed, replace them.
- Update docs based on **code + legacy docs**. Use git diff since last sync commit to focus changes.
- After updates, commit with `docs(docs): sync`.

## Git Strategy

- Always commit after a successful sync.
- Use commit subject to find the last sync:
  - `docs(docs): initial sync`
  - `docs(docs): sync`
- On subsequent runs, diff code and docs since the last sync commit and update docs accordingly.

## Process

### Phase 1: Read Existing Docs (Input)

- Read `README.md`, `AGENTS.md`, and `docs/**/*.md` excluding `docs/` and `docs-3rd/`.
- Extract intent, policies, procedures, roles, and domain language.

### Phase 2: Code Inventory (Targeted Scan)

- Trace entrypoints, adapters, state machines, and core flows.
- Read key tests to capture expected behavior.
- Capture invariants and failure modes from code paths.

### Phase 3: Update Docs

- Create missing docs across the taxonomy.
- Replace or split overgrown docs.
- Ensure coverage across taxonomy categories (policy/standard/guide/procedure/role/checklist/reference/concept/architecture/decision/example/incident/timeline/faq).
- References are for priming; the snippet body must still be self-explanatory.
- Keep `requires` and inline `@...` references relative; tooling resolves them at runtime.

### Phase 4: Index Build

- Always rebuild the index artifact first:
  - `~/.teleclaude/teleclaude/scripts/build_snippet_index.py`
- Rebuild `docs/index.yaml` from docs.
- Ensure IDs and paths are consistent and unique.

### Phase 4.1: Validate

- Validate index and snippet integrity:
  - `~/.teleclaude/teleclaude/scripts/sync_docs.py`

### Phase 5: Report

- Summarize snippet changes.
- List open questions or ambiguous areas.

## Reset Mode (`--reset`)

- Delete or ignore existing docs and regenerate from scratch.
- Recreate baseline, domain structure, and index.
- Only use when the prior snippet set is no longer salvageable.
