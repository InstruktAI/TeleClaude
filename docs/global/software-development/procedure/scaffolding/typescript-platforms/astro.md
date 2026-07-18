---
description: 'Astro scaffolding guidance: the content-site flavor, static-first with opt-in server routes via the Cloudflare adapter.'
visibility: 'public'
---

# TypeScript Astro Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold the content-site flavor: public pages, SEO-first, static output,
server moments only where a route demands one.

## Preconditions

- Portfolio classification: content site (± server moments). App-class
  requirements (auth, payments, dashboards) belong to Next.js instead.
- Check current `npm create astro@latest` options and adapter docs.

## Steps

1. Scaffold with `npm create astro@latest` (strict TypeScript template).
2. `astro check` runs inside `build` — types gate every build.
3. Keep Astro's ESLint/Prettier ecosystem per the base ruling.
4. Interactive chrome stays vanilla script in components; a UI-framework
   island (`client:only`) is added only when a flow genuinely needs one, and
   its styling layer stays scoped to the island.
5. Server moments: add the Cloudflare adapter and make individual routes
   server-rendered — do not switch the site to SSR wholesale.
6. Multi-language sites use Astro i18n routing with
   `prefixDefaultLocale: false`; the full i18n contract comes from the
   frontend production baseline.
7. Wire the baseline's script buttons, sitemap integration, quality gates,
   and CI before feature work.

## Outputs

- A static-first Astro repo with gates and buttons wired, deployable to
  Cloudflare Pages/Workers.

## Recovery

- If a requirement keeps pushing toward app-class (broad SSR, sessions),
  stop and reclassify against the portfolio instead of bending Astro.

## See Also

- ~/.teleclaude/docs/software-development/policy/frontend-production-baseline.md
