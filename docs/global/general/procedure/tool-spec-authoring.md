---
id: 'general/procedure/tool-spec-authoring'
type: 'procedure'
scope: 'global'
description: 'Author lean tool specs under spec/tools while preserving schema compliance and progressive disclosure.'
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
7. Run `telec sync` after updates.

## Outputs

- A discoverable tool spec in `spec/tools/`.
- Updated `spec/tools/baseline.md` ordering if needed.
- Synced artifacts after `telec sync`.

## Recovery

- If docs validation warns on unknown sections, remove non-schema headings.
- If tool details become noisy, split by primitive instead of expanding a single spec.
