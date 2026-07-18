---
description: 'The blessed workload-to-flavor portfolio: which platform each class of project gets and where it deploys. The decision layer the greenfield intake drives.'
---

# Delivery Portfolio — Concept

## What

The portfolio maps **workload classes** to **blessed flavors** and **blessed
delivery targets**. Nobody picks a framework; the intake classifies what the
thing _is_ and the flavor falls out.

| Workload                        | Key question that detects it                            | Flavor                       | Blessed delivery             |
| ------------------------------- | ------------------------------------------------------- | ---------------------------- | ---------------------------- |
| Content site (± server moments) | Public pages, SEO matters, content-first                | Astro (± Cloudflare adapter) | Cloudflare Pages/Workers     |
| Full application                | Auth, payments, dashboards, per-user rendering          | Next.js                      | Container on itsUP           |
| Internal tool UI                | SPA behind a login, SEO irrelevant                      | Vite + React (+ Hono API)    | itsUP or Cloudflare Workers  |
| Public API / functions          | Headless HTTP endpoints                                 | Hono                         | Cloudflare Workers           |
| Systems / daemons               | Runs unattended for months, no UI, failure is expensive | Rust                         | Self-hosted (itsUP / native) |
| Automation / scripts            | One-shot or scheduled glue, ML tooling                  | Python                       | Wherever they run            |

Boundary rules that keep the portfolio sharp:

- **Astro covers the whole content spectrum.** With a server adapter, any route
  can become a Worker function — "content plus a bit of backend" never
  justifies jumping to Next.js.
- **Next.js is purchased complexity.** Server components, caching layers, and
  framework churn pay off only at app-class requirements. Never the default.
- **Vite is never public-facing.** It has no SEO story; it is the
  internal-tool flavor only.
- **Rust never creeps into websites or one-off scripts.** Its iteration cost
  buys nothing there; TypeScript owns the web, Python owns glue.
- **Cloudflare's free tier is the default cloud.** Workers (~100k
  requests/day), KV, D1 (SQLite-class), R2, and cron triggers cover small
  services for free. When a workload needs long-running processes,
  Postgres-class storage, or private infra, the branch points at itsUP.

## Why

Framework choice used to happen in someone's head, invisibly and
inconsistently, and every new repo re-litigated it. Encoding the mapping makes
the greenfield intake a classification exercise with a deterministic outcome,
and gives reviewers a contract to hold delivery against. The table also
records deliberate positions (Astro-over-Next below app-class, free-cloud
first, Rust for systems) so agents stop re-deriving them from training-data
fashion.

## See Also

- ~/.teleclaude/docs/software-development/procedure/greenfield-intake.md — the intake that drives this table.
- ~/.teleclaude/docs/software-development/policy/frontend-production-baseline.md — what every frontend delivery contains.
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md — the button contract and reusable pipelines.
