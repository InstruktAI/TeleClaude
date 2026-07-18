---
description: 'Hono scaffolding guidance: the public API/functions flavor, Workers-native, deployed on the Cloudflare free tier.'
visibility: 'public'
---

# TypeScript Hono Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold the public API flavor: lightweight HTTP endpoints on Cloudflare
Workers — microsecond starts, free tier, no servers to run.

## Preconditions

- Portfolio classification: public API / functions. Needs that exceed the
  Workers model (long-running processes, Postgres-class storage) point at
  itsUP instead.
- Check current `npm create hono@latest` templates and Wrangler docs.

## Steps

1. Scaffold with `npm create hono@latest` (cloudflare-workers template).
2. Framework-neutral repo → Biome; strict TypeScript per the base.
3. Storage from the Workers free tier as needed: KV (config/cache), D1
   (SQLite-class), R2 (files), cron triggers for schedules.
4. Local dev and deploy through Wrangler; secrets via Wrangler secrets, never
   committed.
5. Wire the standard buttons (`e2e` exercises the deployed-shape endpoints)
   and CI with the `deploy-cloudflare` reusable workflow.

## Outputs

- A Hono Workers service with buttons, gates, and CI deploy wired.

## Recovery

- If the service outgrows Workers limits, reclassify delivery to itsUP and
  keep Hono (it runs on Node equally well).

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md
