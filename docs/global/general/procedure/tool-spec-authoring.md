---
description: 'Author lean tool specs under spec/tools while preserving schema compliance and progressive disclosure.'
visibility: 'public'
---

# Tool Spec Authoring — Procedure

## Goal

Create and maintain concise, schema-compliant tool specifications that scale through progressive disclosure.

## Preconditions

- The tool belongs in `docs/global/general/spec/tools/`.
- You are using the existing snippet schema (no custom taxonomy changes).

## Steps

1. Create one tool file per primitive under `spec/tools/`.
2. Keep the tool cabinet manifest in `spec/tools/baseline.md` with ordered `@` references.
3. In each tool spec, keep content lean and use only required spec headings.
4. Place signatures and examples under `Canonical fields` (no extra headings required).
5. Keep `Allowed values` short; if constraints are minimal, state them directly.
6. Document only operational edge cases in `Known caveats`.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

7. Run `telec sync` after updates.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

7. Run bare `telec sync` after updates to validate the authored source; the watcher
   publishes after source activity settles.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Outputs

- A discoverable tool spec in `spec/tools/`.
- Updated `spec/tools/baseline.md` ordering if needed.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Synced artifacts after `telec sync`.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Validated source plus watcher-published artifacts.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Recovery

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- If docs validation reports unknown-section findings, remove non-schema headings — validation always blocks, so `telec sync` (and `--skip-deploy`) fail until they are fixed.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- If docs validation reports unknown-section findings, remove non-schema headings — validation always blocks, so both bare `telec sync` and `telec sync --deploy` fail until they are fixed.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- If tool details become noisy, split by primitive instead of expanding a single spec.
