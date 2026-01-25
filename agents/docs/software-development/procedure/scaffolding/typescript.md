---
description:
  Scaffold a TypeScript repo with standard package scripts, tooling, and
  compiler config.
id: software-development/procedure/scaffolding/typescript
scope: domain
type: procedure
---

# Typescript — Procedure

## Goal

Create a predictable TypeScript project skeleton with standardized tooling and verification commands.

- `package.json` with standard scripts
- `tsconfig.json` as compiler source of truth
- Package manager lockfile (`pnpm-lock.yaml`, `yarn.lock`, or `package-lock.json`)
- Optional wrapper scripts called by package scripts

1. **Initialize project metadata**
   - Create `package.json` with name, version, and scripts.

2. **Define standard scripts**
   - `format` (prettier/biome or configured formatter)
   - `lint` (lint checks)
   - `typecheck` (TypeScript compiler)
   - `test` (unit tests)
   - `test:e2e` (integration tests, if applicable)

3. **Configure compiler**
   - Create `tsconfig.json` with strict settings appropriate for the repo.

4. **Install dependencies**
   - Use the declared package manager (`pnpm`, `yarn`, or `npm`).

5. **Verify scaffold**
   - `pnpm run format`
   - `pnpm run lint`
   - `pnpm run typecheck`
   - `pnpm run test`
   - `pnpm run test:e2e` (if applicable)

- Standard scripts exist and run successfully.
- `tsconfig.json` is present and referenced.
- Lockfile exists and matches package manager.

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
