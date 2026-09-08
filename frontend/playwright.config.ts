import { defineConfig, devices } from '@playwright/test';

const PORT = 3000;
const BASE_URL = `http://localhost:${PORT}`;
const STORAGE_STATE = 'e2e/.auth/state.json';

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts$/,
  // Bounded two-theme visual-regression baselines (agent-vocabulary-single-registry).
  // One flat directory per project keeps the path exactly __screenshots__/<project>/<name>.png.
  snapshotPathTemplate: '{testDir}/__screenshots__/{projectName}/{arg}{ext}',

  globalSetup: require.resolve('./e2e/global-setup.ts'),

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    storageState: STORAGE_STATE,
  },

  webServer: {
    // Direct tsx invocation avoids pnpm's preflight check that fails on
    // ignored-build-scripts warnings; we want to start the same server
    // `pnpm dev` runs without reinstalling dependencies on each test run.
    command: './node_modules/.bin/tsx server.ts',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      ...process.env,
      NEXT_PUBLIC_E2E_FIXTURES: '1',
    },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
