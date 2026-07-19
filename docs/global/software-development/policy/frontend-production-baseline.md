---
description: 'The silent-defaults contract for every delivered frontend site: i18n, SEO, forms, state doctrine, quality gates, and the standard script buttons. Absence of an applicable item is a defect, not a nice-to-have.'
---

# Frontend Production Baseline — Policy

## Rules

Every delivered frontend contains the applicable items below **without the
human asking for them**. The greenfield intake asks only the questions marked
as intake-owned in its procedure; everything here ships in silence. Reviewers
treat the absence of an applicable item as a defect.

### Internationalization (when the site is multi-language)

- One source-of-truth catalog; other locales mirror its shape exactly; the
  type derives from the source catalog so a missing key fails the build.
- Every reader-facing string lives in catalogs — never inline in components.
- Localized URL slugs for every route, with path helpers that translate both
  directions; route files are thin per-locale wrappers around shared page
  components.
- `canonical` + `hreflang` alternates (+ `x-default`) on every page.
- The language switcher operates on the live pathname (pushState-safe); the
  URL wins and updates the stored preference; the stored/browser preference
  redirects only the bare root on arrival.
- Dates, times, and currency always render through `Intl` per locale — never
  hand-formatted.

### SEO and sharing (always)

- One canonical host, decided at intake; the other host 301s with path and
  query preserved.
- Per-page titles and meta descriptions, localized.
- Open Graph + Twitter card meta on every page; a social image (1200×630).
- A sitemap generated from the route tree, and `robots.txt` pointing at it.
- Favicon carries the brand mark and stays legible at 16px.

### Forms (always)

- Semantic HTML5 is non-negotiable: a real `<form>` with a `type="submit"`
  button (Enter submits); every user-data input carries `name`, the correct
  `autocomplete` token, and the right `type`/`inputmode`; labels are real
  `<label>` elements bound to their controls; non-submit buttons inside a form
  say `type="button"`. **Working browser autofill is acceptance criteria** — a
  form that renders correctly but offers no autofill is a defect.
- Validation messages are per-field and specific — never a generic "this field
  is required" for a malformed email.
- Required fields are visibly marked; optional fields say so.
- Multi-step forms carry their step in the URL; answers persist (localStorage)
  with graceful degradation; completion is a routable page, never component
  memory.
- Date fields pair a typed input (autofill-capable) with a calendar picker
  that has year/month dropdowns.

### Client-side state doctrine (always)

- Every navigation state lives in the URL. localStorage is an enhancement with
  graceful degradation, never the carrier of navigation state.
- History traverses correctly: back/forward never strand or duplicate state.

### Time and scheduling UI (when present)

- Slots derive from durations fitting inside availability windows; variable
  durations are an explicit choice control.
- Time navigation is paged (prev/next) with no hard forward cap.
- Live data sources have deterministic fallback and error states.
- Client-side API keys are referrer-restricted with **every** origin
  enumerated: bare domain, www, preview domains, and localhost dev ports.

### Quality gates (always, wired before feature work)

- A visual snapshot suite: every page × theme against committed baselines;
  re-baselining ships in the same commit as the intended change — the commit
  is the approval.
- The visual suite walks the **built sitemap** for its URL set (multiplied by
  themes; locales come free) — no hand-maintained route table, and a page
  that falls out of the sitemap surfaces as a vanished snapshot.
- Determinism is mandatory: external hosts blocked in-test, animations
  disabled, fixed viewport and device scale.
- The visual suite is a **local instrument** (platform-keyed baselines); the
  smoke suite — every page returns 200, applies its stylesheet, logs zero
  console/page errors — is the **CI gate** that blocks deploy.
- CI/CD from day one: deploy on push, after the gates.

### Accessibility (always)

- Semantic landmarks and heading order, alt text on images, ARIA on
  interactive chrome, keyboard operability, visible focus states.

### The standard buttons (always)

`package.json` scripts every frontend repo exposes (manager-agnostic):

```
dev · build · preview
lint · format · typecheck
test · test:visual · test:visual:update · test:smoke
shadcn:add · shadcn:remove        (when shadcn is in play)
```

A five-line Makefile shim maps the TeleClaude contract onto them
(`lint:`/`format:`/`test:` delegate to the package scripts, `e2e:` runs the
heavy suites) so `telec code` and shared CI pipelines work identically across
all repos. Component libraries are vendored through their CLI (pinned as a
devDependency, driven via the scripts) — registry components are never
hand-reconstructed.

## Rationale

This baseline is the codified residue of building a production site while the
human had to drive every invisible default by hand — localized slugs, calendar
paging, autofill semantics, sitemap, social cards, snapshot testing. The
knowledge existed only in a reference repo and the human's patience. As
policy, the defaults ship silently and intake questions shrink to genuine
taste and business decisions.

## Scope

Every frontend delivery (Astro, Next.js, Vite flavors), greenfield or major
rework. Single-language sites skip the i18n section; sites without scheduling
skip that section; everything else always applies.

## Enforcement

- The greenfield intake presents this baseline as silently-delivered scope;
  omitting an applicable item from the plan is a violation.
- Build and commit reviewers treat a missing applicable item as a defect.
- The visual/smoke suites and script buttons are verified present before a
  site's first deploy. A missing-suite finding points at
  `software-development/procedure/setup-visual-regression` as the remediation
  path.

## Exceptions

- Throwaway prototypes explicitly labeled as such by the human.

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md
