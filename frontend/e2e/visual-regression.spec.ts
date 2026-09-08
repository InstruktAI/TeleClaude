import { test, expect } from '@playwright/test';

/**
 * Bounded two-theme visual-regression harness (agent-vocabulary-single-registry).
 *
 * Covers the Preparation panel's existing deterministic `fixtures=smoke` state
 * in both themes — the one key screen this project already has a fixture
 * provider for. There is no equivalent fixture for the Sessions view today
 * (its tree is driven by live daemon/WebSocket state, not a REST fixture), so
 * a Sessions baseline is not included here; see deferrals.md for that gap.
 *
 * Baselines are generated and read by a human before being committed — see
 * software-development/policy/testing "Snapshot approval is a conscious act."
 * Running this file with `--update-snapshots` is not a substitute for that
 * read.
 */

const PREPARATION_URL = '/?panel=preparation&fixtures=smoke';

// The footer reflects live daemon/WebSocket state (real session counts, real
// per-agent availability, real context hints) and is not part of the
// fixture — masked so the baseline is deterministic regardless of which real
// sessions happen to exist when the suite runs. Both rows are masked, not
// just the agent-status strip: hint text length varies with live state too,
// and a narrower mask lets that reflow shift pixels outside its own bounds.
const MASK_TEST_IDS = ['footer-context-row', 'footer-global-row'];

test.describe('preparation panel visual baseline', () => {
  test('light theme', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto(PREPARATION_URL);
    await expect(page.getByTestId('preparation-todo-node').first()).toBeVisible();
    await expect(page).toHaveScreenshot('preparation-light.png', {
      fullPage: true,
      mask: MASK_TEST_IDS.map((id) => page.getByTestId(id)),
    });
  });

  test('dark theme', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto(PREPARATION_URL);
    await expect(page.getByTestId('preparation-todo-node').first()).toBeVisible();
    await expect(page).toHaveScreenshot('preparation-dark.png', {
      fullPage: true,
      mask: MASK_TEST_IDS.map((id) => page.getByTestId(id)),
    });
  });
});
