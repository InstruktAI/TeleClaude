---
id: third-party/playwright/config
type: third-party
scope: project
description: Minimal playwright.config.ts for a Next.js dev server with auto-start webServer and a single chromium project.
---

# Playwright — Config (Next.js dev server)

## What it is

`playwright.config.ts` lives at the project root and is loaded automatically by `playwright test`. It exports the result of `defineConfig({ … })` from `@playwright/test`. The four fields the smoke test needs are `testDir`, `use.baseURL`, `webServer`, and `projects`.

## Minimal config for a Next.js + smoke-test setup

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',

  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },

  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
```

## Field reference

### `testDir`

Directory the runner scans for `*.spec.ts` / `*.test.ts` files. Use a dedicated subtree (`tests/e2e`) so Playwright specs do not collide with Vitest/Jest unit tests.

### `use.baseURL`

Sets the base URL for `page.goto('/some-path')`. When `webServer.url` and `use.baseURL` agree, tests can navigate with relative paths and the runner waits for the server to respond before starting.

### `webServer`

The `webServer` clause auto-starts the Next.js dev server before the test run and tears it down at the end.

- `command: "pnpm dev"` — Next.js dev server. Use `pnpm start` instead if you build first and want to test the production server.
- `url: "http://localhost:3000"` — Playwright polls this URL until it returns a 2xx/3xx response. The default Next.js dev port is 3000.
- `reuseExistingServer: !process.env.CI` — locally, if a dev server is already running on port 3000, Playwright attaches to it instead of spawning a duplicate. On CI (`CI=1`) it always spawns a fresh server, which prevents cross-run state leakage.
- `timeout: 120_000` — milliseconds to wait for the server to become responsive. Cold Next.js dev startup with a fresh `.next/cache` can exceed the default 60 s, so 120 s is the recommended floor.

You can also pass `port` instead of `url` when the server binds to localhost, but `url` is more explicit and works for any host. `stdout`/`stderr` (`'pipe'` or `'ignore'`) control whether server logs are surfaced — leave them at defaults during initial bring-up so failures are visible.

### `projects`

`projects` is an array of named browser configurations. The smoke test only needs one — Chromium with the `Desktop Chrome` device descriptor (sets viewport, user agent, device scale factor):

```typescript
projects: [
  {
    name: 'chromium',
    use: { ...devices['Desktop Chrome'] },
  },
];
```

Run only this project with `pnpm test:e2e --project=chromium`. Add `firefox` / `webkit` projects later if cross-browser coverage becomes a requirement; the smoke test does not need them.

## Caveats

- `webServer.command` is executed via the shell from the project root. Make sure `pnpm dev` works from the repo root before running Playwright — Playwright does not parse package manager errors gracefully.
- If `reuseExistingServer: true` (i.e. local) and stale state in the running dev server causes a flake, kill the dev process before re-running. Playwright will not restart a server it didn't start.
- The runner waits for `webServer.url` to return any successful HTTP status — it does not check that the Next.js page actually rendered. A health-check endpoint is unnecessary for a smoke test, but be aware that "server up" and "app ready" can diverge for a few hundred ms after the URL responds.

## Sources

- https://playwright.dev/docs/test-webserver — `webServer` clause, `reuseExistingServer`, `url` vs `port`
- https://playwright.dev/docs/test-configuration — `defineConfig`, `testDir`, `use.baseURL`, `trace`
- https://playwright.dev/docs/test-projects — `projects` array and `devices` import
- https://playwright.dev/docs/api/class-testconfig — full `TestConfig` reference
