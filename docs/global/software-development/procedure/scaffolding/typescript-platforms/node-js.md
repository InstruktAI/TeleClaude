---
description: Node.js/CLI TypeScript project scaffolding policy.
id: software-development/procedure/scaffolding/typescript-platforms/node-js
scope: domain
type: procedure
---

# TypeScript Node.js Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold a Node.js or CLI TypeScript project with native ESM.

## Preconditions

- Check current Node.js LTS version and its native TypeScript support status (e.g., `--experimental-strip-types`).
- Tooling extends the base:

| Tool              | Purpose                            |
| ----------------- | ---------------------------------- |
| tsx               | Development runner with watch mode |
| `@tsconfig/node*` | Node-specific tsconfig preset      |
| `@types/node`     | Node.js type definitions           |

## Steps

1. Set `"type": "module"` in `package.json`.
2. Extend `@tsconfig/node{version}` for the target Node version.
3. Prefer native TypeScript execution when available; use `tsx` as fallback.
4. Avoid bundlers unless there is a concrete need.
5. Add standard scripts:
   - `pnpm dev`: watch mode with `tsx`
   - `pnpm start`: production execution
   - `pnpm build`: compile with `tsc` (if distributing)

## Outputs

- Native ESM Node.js project
- tsconfig extending Node preset
- Development and production run scripts

## Recovery

- If the project does not run, verify Node version, tsconfig preset, and scripts.
