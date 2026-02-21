# Input: state-yaml-migration

## What we want

Migrate all todo `state.json` files to `state.yaml` across the codebase. YAML is more readable for humans, supports comments, and aligns with `roadmap.yaml` — making the todo system consistent in format. This enables better collaboration between AI agents and human collaborators who inspect and edit state files directly.

## Why

- `state.json` is the only JSON file in the todo system — `roadmap.yaml` is already YAML.
- YAML supports inline comments, making it easier for humans to annotate state during review.
- YAML is more compact and readable for the key-value structures in state files.
- AI agents handle both formats equally well; humans strongly prefer YAML for manual inspection.

## Scope

- Rename `state.json` → `state.yaml` everywhere (scaffold, types, readers, writers, commands).
- Migrate existing `todos/*/state.json` files to `state.yaml`.
- Update all next-machine commands (build, review, fix, finalize, prepare) that read/write state.
- Update tests.
- Keep backward compatibility during transition: reader should fall back to `state.json` if `state.yaml` doesn't exist yet (migration grace period).

## Constraints

- Must not break in-progress todos that have `state.json` but no `state.yaml` yet.
- Pydantic models (`TodoState`, `DorState`, etc.) stay as-is — only serialization format changes.
- No schema changes — pure format migration.
