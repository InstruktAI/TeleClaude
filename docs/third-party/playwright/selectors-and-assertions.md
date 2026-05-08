---
id: third-party/playwright/selectors-and-assertions
type: third-party
scope: project
description: data-testid locators with getByTestId, the four assertions the smoke test needs, and bounding-box layout checks.
---

# Playwright — Selectors and Assertions (smoke-test essentials)

## What it is

Playwright's first-class selector for tests is `page.getByTestId(...)`, which targets the `data-testid` attribute by default. Pair it with web-first assertions from `expect(...)` — they auto-retry until either the condition holds or the assertion timeout (default 5000 ms) expires. For layout assertions that go beyond text and visibility, use `locator.boundingBox()` to read pixel coordinates.

## `data-testid` locators

Add a `data-testid` to any element the test needs to find:

```tsx
// app/preparation/Pane.tsx
<section data-testid="preparation-pane">
  <h2 data-testid="preparation-pane-title">Preparation</h2>
  <button data-testid="preparation-pane-action">Start</button>
</section>
```

Locate it from a test:

```typescript
import { test, expect } from "@playwright/test";

test("preparation pane is visible", async ({ page }) => {
  await page.goto("/");
  const pane = page.getByTestId("preparation-pane");
  await expect(pane).toBeVisible();
});
```

`getByTestId` returns a `Locator` — a lazy, retrying handle to a DOM node. It does not query the DOM until an action or assertion runs, which is what makes Playwright resilient to React re-renders and hydration timing.

Notes:

- The default attribute is `data-testid`. Override globally in `playwright.config.ts` via `use: { testIdAttribute: 'data-test' }` if your codebase uses a different convention. The smoke test sticks to the default.
- Prefer `getByTestId` over CSS selectors (`page.locator('.foo')`) for tests. Test ids decouple the test from styling and structure changes.
- Chain `.getByTestId()` to scope a search inside a parent: `pane.getByTestId('preparation-pane-title')`.

## Assertions

Always `await` `expect(locator).…()` — these are async and auto-retrying. Forgetting `await` produces a passing test that asserts nothing.

### `toBeVisible()`

Checks that the element is attached to the DOM and rendered (non-zero size, not `display: none`, not `visibility: hidden`).

```typescript
await expect(page.getByTestId("preparation-pane")).toBeVisible();
```

### `toContainText(value)`

Substring (or regex) match against the element's text content, including descendants.

```typescript
await expect(page.getByTestId("preparation-pane-title")).toContainText(
  "Preparation"
);

// Regex form
await expect(page.getByTestId("preparation-pane-title")).toContainText(
  /Preparation/i
);
```

Use `toHaveText(value)` instead when the smoke test wants an exact match (rare for prose, useful for status badges).

### `toHaveAttribute(name, value)`

Asserts that an attribute is present with the expected value. The value can be a string or a regex.

```typescript
await expect(page.getByTestId("preparation-pane-action")).toHaveAttribute(
  "type",
  "button"
);

await expect(page.getByTestId("preparation-pane")).toHaveAttribute(
  "aria-busy",
  /^(true|false)$/
);
```

## Layout assertions via `boundingBox()`

For "is element B to the right of element A?" or "is the pane wider than 600 px?" checks, read the bounding box. `locator.boundingBox()` returns `Promise<{ x: number; y: number; width: number; height: number } | null>` — `null` means the element is not visible.

```typescript
test("action button sits inside the pane", async ({ page }) => {
  await page.goto("/");

  const pane = page.getByTestId("preparation-pane");
  const action = page.getByTestId("preparation-pane-action");

  await expect(pane).toBeVisible();
  await expect(action).toBeVisible();

  const paneBox = await pane.boundingBox();
  const actionBox = await action.boundingBox();

  if (!paneBox || !actionBox) {
    throw new Error("expected both elements to be visible");
  }

  // Action is fully contained within the pane.
  expect(actionBox.x).toBeGreaterThanOrEqual(paneBox.x);
  expect(actionBox.y).toBeGreaterThanOrEqual(paneBox.y);
  expect(actionBox.x + actionBox.width).toBeLessThanOrEqual(
    paneBox.x + paneBox.width
  );
  expect(actionBox.y + actionBox.height).toBeLessThanOrEqual(
    paneBox.y + paneBox.height
  );
});
```

Notes:

- Coordinates are pixels relative to the main frame viewport. Scrolling can produce negative `x`/`y`.
- `boundingBox()` is a one-shot read — it does not auto-retry. Anchor the layout check with a preceding `await expect(locator).toBeVisible()` so the layout has settled before reading coordinates.
- Use plain Jest-style `expect(number).toBeGreaterThanOrEqual(...)` for the comparisons. Those are synchronous, non-retrying assertions; combine them with the auto-retrying `toBeVisible()` above to keep the test stable.

## Sources

- https://playwright.dev/docs/locators#locate-by-test-id — `getByTestId`, `testIdAttribute` config
- https://playwright.dev/docs/api/class-locatorassertions — `toBeVisible`, `toContainText`, `toHaveAttribute`
- https://playwright.dev/docs/api/class-locator#locator-bounding-box — `boundingBox()` return shape
- https://playwright.dev/docs/test-assertions — auto-retrying vs one-shot assertions
