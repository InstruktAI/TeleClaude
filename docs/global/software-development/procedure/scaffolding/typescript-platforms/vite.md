---
description: 'Vite + React scaffolding guidance: the internal-tool flavor — SPA behind a login, never public-facing.'
visibility: 'public'
---

# TypeScript Vite + React Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold the internal-tool flavor: a React SPA behind a login. Vite has no
SEO story and is **never chosen for anything public-facing**.

## Preconditions

- Portfolio classification: internal tool UI. Public content belongs to
  Astro; public apps to Next.js.
- Check current `npm create vite@latest` template state and Biome hooks-rule
  coverage.

## Steps

1. Scaffold with `npm create vite@latest --template react-ts`.
2. Framework-neutral repo → Biome as single lint+format tool, with
   `useExhaustiveDependencies` and `useHookAtTopLevel` enabled.
3. When the tool needs an API, pair a Hono service (its own flavor) rather
   than growing a bespoke backend inside the SPA.
4. Wire the standard buttons and CI; the visual/smoke gates apply when the
   tool has meaningful page shapes worth guarding.

## Outputs

- A Vite React SPA for internal use, with buttons and CI wired.

## Recovery

- If SEO or public access requirements appear, stop and reclassify against
  the portfolio.

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
