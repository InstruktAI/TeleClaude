---
description: Vite + React TypeScript project scaffolding policy.
id: software-development/procedure/scaffolding/typescript-platforms/vite
scope: domain
type: procedure
---

# TypeScript Vite + React Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold a Vite-powered React TypeScript project.

## Preconditions

- Check current versions and configs for:
  - Vite and its React template
  - React version and React Compiler status
  - Biome React/hooks rules coverage
- Tooling extends the base:

| Tool           | Purpose                          |
| -------------- | -------------------------------- |
| Vite           | Build tool and dev server        |
| React          | UI library (use latest stable)   |
| React Compiler | Automatic memoization (optional) |

## Steps

1. Start with `pnpm create vite@latest --template react-ts`, then customize.
2. Replace Vite's ESLint with Biome.
3. Enable React Compiler only if the project benefits from automatic memoization.
4. Enable Biome hooks rules: `useExhaustiveDependencies` and `useHookAtTopLevel`.
5. If using React Compiler, add `eslint-plugin-react-hooks` alongside Biome for compiler diagnostics only (or accept the gap).
6. Add standard scripts:
   - `dev`: Vite dev server
   - `build`: production build
   - `preview`: preview production build

## Outputs

- Vite + React project
- Biome replacing ESLint
- Optional React Compiler integration

## Recovery

- If scaffolding fails, re-check tool versions and rerun the steps.
