---
description: 'Next.js TypeScript project scaffolding policy.'
id: 'software-development/procedure/scaffolding/typescript-platforms/next-js'
scope: 'domain'
type: 'procedure'
---

# TypeScript Next.js Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold a Next.js TypeScript project with App Router.

## Preconditions

- Check current versions and configs for:
  - Next.js and its create-next-app options
  - React Compiler integration status in Next.js
  - Biome compatibility with Next.js
- Tooling extends the base:

| Tool           | Purpose                          |
| -------------- | -------------------------------- |
| Next.js        | React framework                  |
| React Compiler | Built-in support via next.config |

## Steps

1. Start with `pnpm create next-app@latest`, then customize.
2. Use App Router only (do not use Pages Router).
3. Replace Next.js ESLint with Biome.
4. Enable React Compiler in `next.config`:

   ```typescript
   experimental: {
     reactCompiler: true;
   }
   ```

5. Let Next.js manage `tsconfig`; extend instead of replacing.
6. Add standard scripts:
   - `dev`: Next.js dev server
   - `build`: production build
   - `start`: production server

## Outputs

- Next.js App Router project
- Biome replacing ESLint
- React Compiler enabled
- Next.js-managed tsconfig

## Recovery

- If scaffolding fails, re-check tool versions and rerun the steps.
