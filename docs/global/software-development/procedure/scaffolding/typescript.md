---
description: 'Base TypeScript project scaffolding policy.'
id: 'software-development/procedure/scaffolding/typescript'
scope: 'domain'
type: 'procedure'
---

# TypeScript Scaffolding — Procedure

## Goal

Establish baseline TypeScript project with modern tooling. Platform-specific files extend this base.

## Preconditions

- Use web search or Context7 to validate current best practices. Do not rely solely on training data — tooling evolves quickly.
- Tooling is available:

| Tool       | Purpose              |
| ---------- | -------------------- |
| pnpm       | Package manager      |
| Biome      | Linting + formatting |
| TypeScript | Type checking        |

## Steps

1. Use Biome as the single lint + format tool (do not combine ESLint + Prettier).
2. Enable strict TypeScript settings including `strict` and `noUncheckedIndexedAccess`.
3. Set `noEmit: true` so bundlers control build output.
4. Ensure standard scripts exist: `format`, `lint`, `typecheck`.

## Outputs

- `package.json` with standard scripts
- `biome.json` with recommended rules
- `tsconfig.json` with strict settings
- `pnpm-lock.yaml`

## Pre-completion checklist

- `pnpm format`
- `pnpm lint`
- `pnpm typecheck`

## Recovery

- If any script fails, correct the tooling/configuration and rerun the checklist.
