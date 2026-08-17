---
description: 'Onboard a project onto the Makefile contract, align the tools behind it toward blessed defaults, and author its checkpoint maintenance overlay from that contract — apply where missing or weaker, ask only on genuine conflict, never overwrite deliberate project-owned config.'
visibility: 'public'
---

# Code Config Assessment — Procedure

## Required reads

@~/.teleclaude/docs/software-development/policy/language-policy-ownership.md

## Goal

Get a project onto the platform's only mandate — a language-agnostic `Makefile`
exposing `install` / `lint` / `test` / `format` — and then align the tools behind
those targets toward TeleClaude's blessed defaults. From that same Makefile
contract it authors the project's checkpoint maintenance overlay — the
`ProjectConfig.checkpoint` config the checkpoint engine consumes. The routine is a
steward: it applies a default where the project is missing or weaker, asks the
human only on a genuine conflict, and never silently overwrites deliberate,
project-owned config.
It is idempotent: a re-run re-checks the gate and proposes only what is still
missing or weaker.

## Preconditions

- The current working directory is the project root.

- The Makefile lifecycle template is language-neutral at `templates/quality/Makefile.template`
  and is scaffolded for every adopting project regardless of detected language. Per-language
  blessed config defaults live under `templates/quality/{flavor}/` in the TeleClaude repo.

- Blessed defaults also include a language-neutral `.gitignore` base plus per-language
  additions (`templates/quality/gitignore`, `templates/quality/{flavor}/gitignore`), merged
  **additively** into the project's `.gitignore` on adoption — never copied over a file the
  project already owns. Language-specific dependencies and behavior come from the applicable
  language policy and its blessed template; this coordinator does not restate them.

- The Makefile-mandate contract is `software-development/design/project-toolchain`:
  the `Makefile` is the only mandate; the tools behind it are detected and offered,
  never prescribed.

- The checkpoint overlay contract is `project/procedure/checkpoint-overlay-projection`,
  `project/design/architecture/checkpoint-system` (the code-agnostic base overlay
  mechanism), and `project/spec/domain/config` (`ProjectConfig.checkpoint`): the overlay
  this procedure authors is config, and it lands in `teleclaude.yml`.

## Steps

### 1. Detect the project's languages and surfaces

Detect languages from repo artifacts (`pyproject.toml` / `setup.py` / root Python
→ python; `tsconfig.json` or `package.json` with a typescript dep → typescript;
`Cargo.toml` → rust). Read `frontend_root` from `teleclaude.yml` if present,
defaulting to `frontend`.

### 1b. Author the project's capability toggles

Write the project's three capability toggles into `teleclaude.yml` from what the
repo actually holds (`project/spec/feature/config/project-capability-manifest`):

- **`code`** — the repo carries a make contract or a language tree detected in
  step 1. A repository with neither holds no code under the TeleClaude lifecycle,
  and the whole code pipeline stays off: no sealed-commit surface, no quality
  lanes, no git hooks, no toolchain or test maintenance.
- **`docs`** — snippet frontmatter exists under `docs/`.
- **`agents`** — agent artifacts exist under `agents/` or `.agents/`.

Task tracking carries no toggle: a project holding a `teleclaude.yml` subscribes
it by that fact alone.

The **initial** toggles are already written at onboard by `telec projects init`,
which performs the same deterministic structural inference before any
capability-gated plumbing installs. This step **re-checks and refines** them —
adjusting a toggle only on a grounded signal, and recording a genuinely ambiguous
capability for human confirmation rather than guessing. Either way the inference
is structural (file existence), never a runtime code path and never a semantic
judgment; the runtime reads only the written declaration.


After writing the toggles, run `telec sync`: its mutating path (after the read-only `--skip-deploy` early return) projects the declaration
into the git-directory capability markers and sets the docs filter driver present
iff `docs` is subscribed. That is the single durable projection boundary — you do
not hand-write markers. Never edit a project-tracked file to reflect a toggle:
capability state lives in TeleClaude's own git territory, and the `.gitattributes`
docs line is written once at onboard and left alone thereafter.

### 2. Makefile contract gate (ordered prerequisite)

Bring the project onto the Makefile contract **before** any config alignment. The
steps are ordered; each depends on the one before it.

1. **`Makefile` exists?** Greenfield: scaffold the language-neutral lifecycle template from
   `templates/quality/Makefile.template`. Brownfield: create it by wiring the project's
   **existing** lint/test entrypoints under `make lint` / `make test` (and
   `install` / `format`) — wrap what the project already runs, do not replace it.

2. **`make lint` and `make test` exist?** If a target is absent, add and wire it to
   the project's native tooling.
3. **Targets honor the adoption contract.** `make lint` and `make format` read an
   optional `FILES_FROM` scope and run the whole suite when it is absent;
   `make install` / `make test` run with no args. `FILES_FROM` holds the **path to a
   temp file** whose contents are the scoped paths, **NUL-terminated** — the paths
   never arrive as make goals or on the command line. This `FILES_FROM`/no-args
   contract is what lets `telec code` scope through `make` (see
   `software-development/design/project-toolchain`).

   Wiring a lint or format target that ignores `FILES_FROM` is a **defect, not a
   simplification**: the scope `telec code` resolved is silently discarded and the
   recipe checks the whole tree, so a commit fails on files it never touched and any
   concurrent session's in-flight work blocks this one. Read the scope in the recipe's
   delegated script:

   ```bash
   paths=()
   if [ -n "${FILES_FROM:-}" ]; then
       while IFS= read -r -d "" path; do paths+=("$path"); done < "$FILES_FROM"
   fi
   ```

   Then bucket `paths` by extension and pass each bucket to the tool that owns it,
   **skipping a tool entirely when its bucket is empty**. A whole-project typechecker
   that cannot take a file subset (`tsc -b`, `mypy` in daemon mode) is skipped when the
   scope contains none of its language — never widened back to the whole tree. With no
   `FILES_FROM`, run everything.

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

### 5. Author the checkpoint maintenance overlay

With the Makefile contract established (Step 2), author the project's checkpoint
maintenance overlay into its `teleclaude.yml` (`ProjectConfig.checkpoint`)
following `project/procedure/checkpoint-overlay-projection`.

**The `code` scope is the project's entire source surface — every language and
file type — authored as broad source-root _directory_ globs.** TeleClaude is
code-agnostic: `code` is never "the detected language" and never an extension
filter. A project's Python, shell, templates, Dockerfiles, and config-as-code are
all `code`; scoping it by extension (e.g. `**/*.py`) is a bug that silences every
other source file. Enumerate the real source directories; exclude only what is
genuinely not source — generated artifacts, vendored trees, and the separate
`tests` category.

Know what the `code` scope drives and what it does not
(`project/design/architecture/checkpoint-system`, Inv 24–25):

- It feeds three consumers — the `agent_stop` hook (`test` + `log-check`), the
  commit-obligation ledger, and integrator post-merge maintenance. Under-scoping
  it under-covers all three.
- It does **not** gate review. The post-commit review gate fires for any committed
  file that is not documentation (`docs/**`, `*.md`, `*.txt`, `*.rst`) —
  code-agnostic and independent of this overlay — so reviewers already see
  everything. Never scope `code` narrowly to "control review"; you cannot.

Then declare the project's own runtime maintenance actions (validate, build,
restart, reload) as `actions` and bind them to the paths that owe them, so the
checkpoint engine nudges the project's own maintenance on top of the
platform-universal base. The overlay is config — it lands in `teleclaude.yml`,
the surface this procedure owns. Record any source-root or runtime-command
uncertainty for human confirmation rather than guessing; this is authoring-time
intelligence, never a runtime detection path (`general/principle/intelligence-boundaries`).

### 6. Re-run safely

The routine is idempotent. A re-run re-checks the Makefile contract gate, the
config comparison, and the checkpoint overlay, and proposes only what is still
missing or weaker; matching settings and already-wired targets are left
untouched.

## Outputs

- The project on the Makefile contract (`install` / `lint` / `test` / `format`
  present, `make lint` and `make format` honoring the `FILES_FROM`/no-args adoption
  contract).
- Tool configs raised toward the blessed defaults where they were missing or
  weaker, with deliberate project-owned config preserved.
- The project's checkpoint maintenance overlay authored into `teleclaude.yml`
  (`ProjectConfig.checkpoint`), so the checkpoint engine gates on the project's
  actual actions rather than the base-only fallback.
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
