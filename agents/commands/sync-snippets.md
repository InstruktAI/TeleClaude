---
description: Generate or refresh atomic docs/snippets from the codebase for AI context selection.
argument-hint: "[scope|--reset]"
---

# Synchronize Snippets

Create or update `docs/snippets/` to reflect the actual architecture and behavior of the codebase. Snippets are the single source of truth for AI context selection.

## Scope

Scope: "$ARGUMENTS"

- Scope: optional focus area (path, feature, or component). If omitted, cover the whole repo.
- If scope includes `--reset`, rebuild snippets from scratch (destructive). Use only after major refactors.

## Snippet Authoring Reference

@docs/snippets/guide/snippet-authoring.md

Read the snippet indexes to learn what exists:

- `docs/global-snippets/index.yaml`
- `docs/snippets/index.yaml`

## Directory Convention

- `docs/snippets/` — output only (do NOT read as input)
- Use other documentation as input: `README.md`, `AGENTS.md`, `docs/**/*.md` except `docs/snippets/` and `docs/3rd-party/`
- `docs/3rd-party/` is external research; never use it as input

## State-Based Workflow

### State A: No `docs/snippets/` (legacy repo)

- **Ignore existing docs/snippets** (none yet).
- Read legacy docs (`docs/**/*.md` excluding `docs/snippets/` and `docs/3rd-party/`).
- Read codebase using targeted scanning (entrypoints, core modules, adapters, tests).
- Build snippets from **code + legacy docs**.
- Create an initial sync commit: `docs(snippets): initial sync`.

### State B: `docs/snippets/` exists

- **Do not trust existing snippets**. This is the most important case.
- Start by auditing code + legacy docs; treat existing snippets as output only.
- If existing snippets are incomplete or skewed, replace them.
- Update snippets based on **code + legacy docs**. Use git diff since last sync commit to focus changes.
- After updates, commit with `docs(snippets): sync`.

## Git Strategy

- Always commit after a successful sync.
- Use commit subject to find the last sync:
  - `docs(snippets): initial sync`
  - `docs(snippets): sync`
- On subsequent runs, diff code and docs since the last sync commit and update snippets accordingly.

## Process

### Phase 1: Read Existing Docs (Input)

- Read `README.md`, `AGENTS.md`, and `docs/**/*.md` excluding `docs/snippets/` and `docs/3rd-party/`.
- Extract intent, policies, procedures, roles, and domain language.

### Phase 2: Code Inventory (Targeted Scan)

- Trace entrypoints, adapters, state machines, and core flows.
- Read key tests to capture expected behavior.
- Capture invariants and failure modes from code paths.

### Phase 3: Update Snippets

- Create missing snippets across the taxonomy.
- Replace or split overgrown snippets.
- Ensure coverage across taxonomy categories (policy/standard/guide/procedure/role/checklist/reference/concept/architecture/decision/example/incident/timeline/faq).
- References are for priming; the snippet body must still be self-explanatory.
- Keep `requires` and inline `@...` references relative; tooling resolves them at runtime.

### Phase 4: Index Build

- Always rebuild the index artifact first:
  - `~/.teleclaude/teleclaude/scripts/build_snippet_index.py`
- Rebuild `docs/index.yaml` from snippets.
- Ensure IDs and paths are consistent and unique.

### Phase 4.1: Validate

- Validate index and snippet integrity:
  - `~/.teleclaude/teleclaude/scripts/sync_snippets.py`

### Phase 5: Report

- Summarize snippet changes.
- List open questions or ambiguous areas.

## Reset Mode (`--reset`)

- Delete or ignore existing snippets and regenerate from scratch.
- Recreate baseline, domain structure, and index.
- Only use when the prior snippet set is no longer salvageable.
