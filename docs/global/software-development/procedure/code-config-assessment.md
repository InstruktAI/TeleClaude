---
description: 'Assess a project''s tool configuration against blessed templates and report coverage gaps.'
visibility: 'public'
---

# Code Config Assessment — Procedure

## Goal

Compare a project's tool configuration against TeleClaude's blessed
templates and produce a coverage report with actionable recommendations.

## Preconditions

- The current working directory is the project root.
- Blessed templates exist under `templates/quality/{language}/` in the TeleClaude repo.

## Steps

1. Detect languages from repo artifacts (`pyproject.toml`, `setup.py`, or root Python files → python; `tsconfig.json` or `package.json` with typescript dep → typescript; `Cargo.toml` → rust). Read `frontend_root` from `teleclaude.yml` if present, defaulting to `frontend`.
2. For each declared language, read the project's tool configs:
   - **Python**: `pyproject.toml` sections for ruff, pyright, mypy, guardrails.
   - **TypeScript**: `tsconfig.json`, `eslint.config.mjs`, `.prettierrc`,
     `vitest.config.ts` (all relative to `frontend_root`).
   - **Rust**: `Cargo.toml` (`[lints]` / `[workspace.lints]`), `rustfmt.toml`,
     `clippy.toml`, resolved from the Cargo workspace root.
3. Read the blessed templates from `templates/quality/{language}/`. If no blessed
   template exists for a declared language, report that absence as a gap.
4. Compare semantically — coverage analysis, not file diff:
   - Which rules/sections are present vs missing?
   - Is strict mode enabled (pyright, tsconfig)?
   - Are clippy lints denied at the workspace level (`-D warnings`)?
   - Are key safety settings active?
5. Report findings per language with sections: **Present** (matching rules),
   **Missing or Weaker** (gaps), **Recommendations** (actionable items). Focus on
   safety-impacting settings (strict mode, type checking, lint rules).
6. Apply recommended changes only after the user approves via session interaction.

## Outputs

- A per-language coverage report (Present / Missing or Weaker / Recommendations).
- Config changes applied only on explicit approval.

## Recovery

- You are an assessor, not an applier. The failure mode is modifying config files
  before presenting findings. If you catch yourself about to write a config change
  without an approval in the conversation, stop and report first.
