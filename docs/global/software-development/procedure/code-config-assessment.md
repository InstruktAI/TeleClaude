---
description: 'Onboard a project onto the Makefile contract, then assess and align the tools behind it against blessed defaults — apply where missing or weaker, ask only on genuine conflict, never overwrite deliberate project-owned config.'
visibility: 'public'
---

# Code Config Assessment — Procedure

## Goal

Get a project onto the platform's only mandate — a language-agnostic `Makefile`
exposing `install` / `lint` / `test` / `format` — and then align the tools behind
those targets toward TeleClaude's blessed defaults. The routine is a steward: it
applies a default where the project is missing or weaker, asks the human only on a
genuine conflict, and never silently overwrites deliberate, project-owned config.
It is idempotent: a re-run re-checks the gate and proposes only what is still
missing or weaker.

## Preconditions

- The current working directory is the project root.

- The Makefile lifecycle template is language-neutral at `templates/quality/Makefile.template`
  and is scaffolded for every adopting project regardless of detected language. Per-language
  blessed config defaults live under `templates/quality/{flavor}/` in the TeleClaude repo.

- The Makefile-mandate contract is `software-development/design/project-toolchain`:
  the `Makefile` is the only mandate; the tools behind it are detected and offered,
  never prescribed.

## Steps

### 1. Detect the project's languages and surfaces

Detect languages from repo artifacts (`pyproject.toml` / `setup.py` / root Python
→ python; `tsconfig.json` or `package.json` with a typescript dep → typescript;
`Cargo.toml` → rust). Read `frontend_root` from `teleclaude.yml` if present,
defaulting to `frontend`.

### 2. Makefile contract gate (ordered prerequisite)

Bring the project onto the Makefile contract **before** any config alignment. The
steps are ordered; each depends on the one before it.

1. **`Makefile` exists?** Greenfield: scaffold the language-neutral lifecycle template from
   `templates/quality/Makefile.template`. Brownfield: create it by wiring the project's
   **existing** lint/test entrypoints under `make lint` / `make test` (and
   `install` / `format`) — wrap what the project already runs, do not replace it.

2. **`make lint` and `make test` exist?** If a target is absent, add and wire it to
   the project's native tooling.
3. **Targets honor the adoption contract.** `make lint` accepts an optional
   `FILES="…"` scope and runs the whole suite with no args; `make install` /
   `make test` / `make format` run with no args. This `FILES=`/no-args contract is
   what lets `telec code` scope through `make` (see
   `software-development/design/project-toolchain`).
4. **Only then** proceed to config alignment (Step 3).

### 3. Align tool configs toward blessed defaults

For each detected language, read the project's tool configs and compare them
semantically — coverage, not file diff — against the blessed defaults under
`templates/quality/{flavor}/`:

- **Python**: `pyproject.toml` sections for ruff, pyright, mypy.
- **TypeScript**: `tsconfig.json`, the chosen linter/formatter config (ESLint +
  Prettier or Biome — the project's call), `vitest.config.ts` (relative to
  `frontend_root`).
- **Rust**: `Cargo.toml` lints, `rustfmt.toml`, `clippy.toml`, from the Cargo
  workspace root.

Classify each setting and target, then steward toward the best outcome:

- **Missing or weaker → apply it.** Adoption, not overwrite; propose and merge
  additively, no question needed.
- **Conflict** (a deliberate, defensible divergence the default would override)
  **→ surface and ask** the human, framed as a recommendation ("I'd adopt X
  because Y — keep your local choice?"), never a menu. Warn when a default would
  carry an impact the project does not want.
- **Matching → no-op.**

### 4. Guardrails need no project config

Do not add a `teleclaude.yml` guardrails section, and do not seed guardrails
defaults into the project. Guardrails are TeleClaude-owned and run automatically
as the always-run lane of `telec code lint`; they reach a project simply by the
project being run under `telec code`, with no per-project quality-config surface.

### 5. Re-run safely

The routine is idempotent. A re-run re-checks the Makefile contract gate and the
config comparison and proposes only what is still missing or weaker; matching
settings and already-wired targets are left untouched.

## Outputs

- The project on the Makefile contract (`install` / `lint` / `test` / `format`
  present, `make lint` honoring the `FILES=`/no-args adoption contract).
- Tool configs raised toward the blessed defaults where they were missing or
  weaker, with deliberate project-owned config preserved.
- A short record of what was applied and what was surfaced for the human's
  decision.

## Recovery

- The invariant: **never silently overwrite an intentional divergence.** Applying
  a default where the project is missing or weaker is correct and expected; on a
  genuine conflict, surface a recommendation and let the human decide. If you
  catch yourself about to overwrite a deliberate project choice, stop and ask.
- If the Makefile contract gate cannot be satisfied (no detectable native lint/test
  entrypoint to wrap), report the gap rather than fabricating targets that run
  nothing.

## Discipline

The failure mode this procedure guards against is aligning configs before the
project is on the Makefile contract — tuning tools behind a plug that does not
exist — and overwriting deliberate project-owned config in the name of "blessed
defaults." The gate is ordered for that reason: Makefile first, adoption contract
second, alignment last. The steward applies defaults only where the project is
missing or weaker, and treats a deliberate divergence as the human's call, not a
gap to close.
