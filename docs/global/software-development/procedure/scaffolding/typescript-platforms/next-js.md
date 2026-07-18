---
description: 'Next.js scaffolding guidance: the app-class flavor — auth, payments, dashboards — delivered as a container on itsUP.'
visibility: 'public'
---

# TypeScript Next.js Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold the app-class flavor. Next.js is purchased complexity — chosen only
when app requirements (auth, payments, per-user rendering) amortize it.

## Preconditions

- Portfolio classification: full application. Content-first work belongs to
  Astro.
- Check current `create-next-app@latest` options, React Compiler status, and
  App Router guidance.

## Steps

1. Scaffold with `create-next-app@latest`; App Router only.
2. Keep the framework's lint ecosystem (ESLint + Prettier) per the base
   ruling; let Next.js manage `tsconfig` and extend it.
3. Enable React Compiler when the current Next.js release marks it stable
   for the project's needs.
4. Delivery is a container on itsUP: add the Dockerfile (standalone output)
   and wire the repo to the itsUP reconcile workflow
   (`Morriz/itsUP` `reconcile.yml`, `secrets: inherit`, `APP_NAME` set).
5. Wire the frontend baseline's applicable branches (SEO, forms, gates,
   buttons) and CI before feature work.

## Outputs

- A Next.js App Router repo, containerized, gated, deploying to itsUP.

## Recovery

- If the app-class requirements evaporate during intake, reclassify to Astro
  before writing features — not after.

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
- ~/.teleclaude/docs/software-development/policy/frontend-production-baseline.md
