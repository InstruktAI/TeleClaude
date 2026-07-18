---
description: 'Base TypeScript project guidance: generator-first scaffolding, quality requirements, and the rulings on package managers and lint tooling.'
visibility: 'public'
---

# TypeScript Scaffolding — Procedure

## Goal

Establish the shared TypeScript ground rules every platform flavor builds on.
Flavors prescribe _qualities and buttons_; the framework's own generator owns
the files.

## Preconditions

- The workload is classified per the delivery portfolio and a platform flavor
  is chosen — this base is never scaffolded alone.
- Verify current generator/tooling state with a quick search; generators and
  flags churn faster than training data.

## Steps

1. **Scaffold with the framework's own generator, always** — the current
   `npm create` / `create-next-app` incantation for the chosen flavor. Never
   deploy scaffold files from a blessed folder — a baked scaffold is a stale
   cache of the generator.
2. **Package manager ruling**: pnpm blessed for greenfield; in any existing
   repo the lockfile is law; never mix. The button contract is
   manager-agnostic, so this choice never leaks into scripts or CI.
3. **Lint/format ruling**: where the framework has a first-class lint
   ecosystem (Astro, Next.js), keep it (ESLint + Prettier). Where the repo is
   framework-neutral (Hono services, Vite tools, CLIs), use Biome as the
   single lint+format tool. The qualities are non-negotiable either way: one
   formatter, strict TypeScript (`strict`, `noUncheckedIndexedAccess`), types
   checked in CI.
4. **Standard scripts exist regardless of flavor**: `dev`, `build`, `lint`,
   `format`, `typecheck`, `test` — plus the flavor's additions. A thin
   Makefile shim maps `lint`/`format`/`test`/`e2e` onto them for `telec code`
   and shared CI (see the CI pipeline conventions policy).
5. **Quality gates are wired before feature work**, per the applicable
   production baseline.

## Outputs

- A generator-produced repo meeting the qualities above, with the button set
  and Makefile shim in place.

## Recovery

- If generator output conflicts with these rules, prefer the generator's
  ecosystem convention and satisfy the _quality_ another way; record the
  deviation in the repo's AGENTS.md.

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md
