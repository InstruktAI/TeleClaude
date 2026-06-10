---
description: 'Steward a project''s tool configuration toward blessed defaults — apply where missing or weaker, ask only on conflict.'
visibility: 'public'
---

# Code Config Assessment — Procedure

## Goal

Steward a project's tool configuration toward TeleClaude's blessed defaults: apply a
default where the project is missing or weaker, ask the human only on a genuine
conflict, and never silently overwrite deliberate, project-owned config.

## Preconditions

- The current working directory is the project root.
- Blessed defaults exist under `templates/quality/{language}/` in the TeleClaude repo.

## Steps

1. Detect languages from repo artifacts (`pyproject.toml` / `setup.py` / root Python → python; `tsconfig.json` or `package.json` with a typescript dep → typescript; `Cargo.toml` → rust). Read `frontend_root` from `teleclaude.yml` if present, defaulting to `frontend`.
2. For each declared language, read the project's tool configs:
   - **Python**: `pyproject.toml` sections for ruff, pyright, mypy, guardrails.
   - **TypeScript**: `tsconfig.json`, the chosen linter/formatter config (ESLint+Prettier or Biome — the project's call), `vitest.config.ts` (relative to `frontend_root`).
   - **Rust**: `Cargo.toml` lints, `rustfmt.toml`, `clippy.toml`, from the Cargo workspace root.
3. Read the blessed defaults from `templates/quality/{language}/`. Also ensure the project's `Makefile` exposes `install` / `test` / `lint` / `format` — the only mandate (see `software-development/design/project-toolchain`).
4. Compare semantically, per setting and target:
   - **Missing or weaker** — the project lacks a blessed setting/target, or has a weaker one.
   - **Conflict** — the project has a deliberate, defensible divergence the default would override.
   - **Matching** — present and equivalent.
5. **Steward toward the best outcome:**
   - **Missing or weaker → apply it.** Adoption, not overwrite; no question needed.
   - **Conflict → surface and ask** the human, framed as a recommendation ("I'd adopt X because Y — keep your local choice?"), never a menu.
   - **Matching → no-op.**
6. Generate or adapt the `Makefile` toward the language-agnostic flavor where it is missing or incomplete; leave deliberate, project-owned config untouched.

## Outputs

- The project raised toward the blessed defaults where it was missing or weaker.
- A short record of what was applied and what was surfaced for the human's decision.

## Recovery

- The invariant: **never silently overwrite an intentional divergence.** Applying a default where the project is missing or weaker is correct and expected; on a genuine conflict, surface a recommendation and let the human decide. If you catch yourself about to overwrite a deliberate project choice, stop and ask.
