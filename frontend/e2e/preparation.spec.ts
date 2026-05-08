import { test, expect } from "@playwright/test";

const SMOKE_URL = "/?panel=preparation&fixtures=smoke";

test("preparation pane renders the todo tree (SC-2/SC-8)", async ({ page }) => {
  await page.goto(SMOKE_URL);

  const treeNodes = page.getByTestId("preparation-todo-node");
  await expect(treeNodes.first()).toBeVisible();
  expect(await treeNodes.count()).toBeGreaterThanOrEqual(2);
});

test("preparation pane renders status block characters (SC-5)", async ({ page }) => {
  await page.goto(SMOKE_URL);

  const block = page.getByTestId("status-block").first();
  await expect(block).toBeVisible();
  const text = (await block.textContent()) ?? "";
  expect(text).toMatch(/[█□]/);
});

test("preparation pane aligns phase indicators across todos with different slug lengths (SC-6)", async ({
  page,
}) => {
  await page.goto(SMOKE_URL);

  // smoke-active-row (16 chars) and smoke-x (8 chars) both render the same
  // prepare:discovery indicator, so SC-6 checks that the indicator's left
  // edge is at the same x in both rows even though the slugs differ.
  const longRowIndicator = page.locator(
    '[data-testid="preparation-todo-node"][data-slug="smoke-active-row"] [data-testid="phase-indicator"]',
  );
  const shortRowIndicator = page.locator(
    '[data-testid="preparation-todo-node"][data-slug="smoke-x"] [data-testid="phase-indicator"]',
  );

  await expect(longRowIndicator).toBeVisible();
  await expect(shortRowIndicator).toBeVisible();

  const longBox = await longRowIndicator.boundingBox();
  const shortBox = await shortRowIndicator.boundingBox();
  expect(longBox).not.toBeNull();
  expect(shortBox).not.toBeNull();
  // 1px tolerance for subpixel rendering; failure means the slug-column-width
  // contract did not actually freeze the column origin across rows.
  expect(Math.abs(longBox!.x - shortBox!.x)).toBeLessThanOrEqual(1);
});

test("preparation pane encodes status-block colors for delivered, active, and draft rows (SC-5/SC-7)", async ({
  page,
}) => {
  await page.goto(SMOKE_URL);

  const delivered = page.locator(
    '[data-testid="preparation-todo-node"][data-slug="smoke-delivered-row"] [data-testid="status-block"]',
  );
  const active = page.locator(
    '[data-testid="preparation-todo-node"][data-slug="smoke-active-row"] [data-testid="status-block"]',
  );
  const draft = page.locator(
    '[data-testid="preparation-todo-node"][data-slug="smoke-draft-row"] [data-testid="status-block"]',
  );

  await expect(delivered).toBeVisible();
  await expect(active).toBeVisible();
  await expect(draft).toBeVisible();

  await expect(delivered).toHaveAttribute("data-color", "green");
  await expect(active).toHaveAttribute("data-color", "gold");
  await expect(draft).toHaveAttribute("data-color", "gray");
});
