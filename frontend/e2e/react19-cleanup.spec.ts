import { test, expect } from "@playwright/test";

test.describe("React 19 Lint Cleanup Smoke", () => {
  test("session tree navigation and theming toggle", async ({ page }) => {
    await page.route("**/api/computers", async (route) => {
      await route.fulfill({
        json: [
          {
            name: "local",
            status: "online",
            user: "tester",
            host: "localhost",
            is_local: true,
          },
        ],
      });
    });
    await page.route("**/api/sessions**", async (route) => {
      await route.fulfill({
        json: [
          {
            session_id: "smoke-session",
            detached: false,
            title: "Smoke session",
            status: "running",
            active_agent: "codex",
            last_input: "Exercise the session tree",
            project_path: "/work/smoke",
            computer: "local",
            created_at: "2026-03-30T12:00:00Z",
          },
        ],
      });
    });

    await page.goto("/");

    await expect(page.getByRole("tablist")).toBeVisible();

    const computerNode = page.locator('[data-testid^="computer-header-"]').first();
    await expect(computerNode).toBeVisible();

    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowUp");

    const themingToggle = page.getByTestId("theming-toggle");
    await expect(themingToggle).toBeVisible();

    const initialLabel = await themingToggle.getAttribute("aria-label");

    await themingToggle.click();

    await expect(themingToggle).not.toHaveAttribute("aria-label", initialLabel || "");
    const newLabel = await themingToggle.getAttribute("aria-label");

    await page.reload();

    await expect(page.getByTestId("theming-toggle")).toBeVisible();
    const reloadedLabel = await page.getByTestId("theming-toggle").getAttribute("aria-label");
    expect(reloadedLabel).toBe(newLabel);
  });
});
