---
id: third-party/playwright/install
type: third-party
scope: project
description: Install @playwright/test via pnpm, install Chromium with system deps, and wire the test:e2e script.
---

# Playwright — Install (pnpm + Next.js)

## What it is

`@playwright/test` is the Playwright test runner. It ships its own runner (`playwright test`), a config file (`playwright.config.ts`), and the `@playwright/test` API (`test`, `expect`, `Page`, `Locator`). Browser binaries are installed separately via the `playwright` CLI.

## Install commands

Add the runner as a dev dependency:

```bash
pnpm add -D @playwright/test
```

Install the Chromium browser binary plus host system libraries (the smoke test only needs Chromium, so skip Firefox and WebKit):

```bash
pnpm exec playwright install --with-deps chromium
```

Notes on `--with-deps`:

- Pulls OS-level dependencies (fonts, codecs, libnss, etc.) needed for headless Chromium.
- Requires `sudo` on Linux. On macOS it's a no-op for system deps but the flag is still accepted.
- On CI and fresh dev machines, always pass `--with-deps`. On a workstation that has previously run Playwright, `pnpm exec playwright install chromium` is sufficient.

## Version pin pattern

Playwright pins the runner and the browser revisions together — a mismatch between `@playwright/test` and the installed browsers produces hard runtime errors. Pin to an exact version (no `^`, no `~`) so `pnpm install` and `playwright install` stay in lock-step:

```jsonc
// package.json (excerpt)
{
  "devDependencies": {
    "@playwright/test": "1.58.2",
  },
}
```

When upgrading, bump the version, run `pnpm install`, then re-run `pnpm exec playwright install --with-deps chromium` to refresh the browser binaries.

## package.json scripts

Add a single script entry. The runner reads `playwright.config.ts` from the project root by default, so no extra flags are needed:

```jsonc
// package.json (excerpt)
{
  "scripts": {
    "test:e2e": "playwright test",
  },
}
```

Invoke with `pnpm test:e2e`. Useful ad-hoc flags (no need to script them):

- `pnpm test:e2e --headed` — run with a visible browser window for debugging.
- `pnpm test:e2e --ui` — open the Playwright UI mode (timeline, locator picker, time-travel).
- `pnpm test:e2e <file>` — run a single spec file.
- `pnpm test:e2e --project=chromium` — restrict to the `chromium` project (matches the smoke-test setup).

## Caveats

- Use `pnpm exec playwright …` (or `pnpm dlx playwright …`) instead of `npx playwright …`. `npx` reaches into the global npm cache and may resolve a different Playwright version than the one pinned in `package.json`, which then mismatches the browser binaries.
- The first `playwright install` writes binaries under `~/.cache/ms-playwright` (Linux/macOS) or `%USERPROFILE%\AppData\Local\ms-playwright` (Windows). Do not commit them.
- If you only need Chromium, do not run the bare `playwright install` — it downloads all three browser families and roughly triples the disk footprint.

## Sources

- https://playwright.dev/docs/intro — Installation
- https://playwright.dev/docs/ci — `--with-deps` and CI install patterns
- https://playwright.dev/docs/best-practices — pnpm install pattern, Chromium-only install
- https://playwright.dev/docs/test-cli — `playwright test` CLI reference
