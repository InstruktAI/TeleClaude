# Implementation Plan: frontend-theming-tui-parity

## Overview

Replace the Next.js frontend's generic shadcn/ui oklch color system with TeleClaude's structural token palette, then layer a two-state theming system (peaceful/themed) on top. The approach builds on existing infrastructure: `tokens.ts` already has all agent colors and structural tokens ported from the TUI, and `css-variables.ts` already generates CSS custom properties. The work is primarily wiring — connecting the existing token data to the CSS layer, adding a boolean theming context, and making components read from CSS variables conditionally.

No new npm packages required. `next-themes` is already installed.

## Phase 1: Base Theme — Replace oklch with TeleClaude Tokens

### Task 1.1: Replace shadcn oklch values in globals.css

**File(s):** `frontend/app/globals.css`

- [x] Replace all oklch values in the `@theme { }` block with TeleClaude structural token hex values for light mode:
  - `--color-background` → `#fdf6e3` (warm paper base)
  - `--color-foreground` → `#303030` (text primary)
  - `--color-card` / `--color-popover` → `#f0ead8` (surface)
  - `--color-card-foreground` / `--color-popover-foreground` → `#303030`
  - `--color-primary` → `#303030` (near-black)
  - `--color-primary-foreground` → `#fdf6e3`
  - `--color-secondary` → `#e8e0cc` (panel)
  - `--color-secondary-foreground` → `#303030`
  - `--color-muted` → `#e8e0cc` (panel)
  - `--color-muted-foreground` → `#808080` (text muted)
  - `--color-accent` → `#e8e0cc`
  - `--color-accent-foreground` → `#303030`
  - `--color-destructive` → `#d70000` (status error)
  - `--color-destructive-foreground` → `#d70000`
  - `--color-border` → `#a8a8a8`
  - `--color-input` → `#a8a8a8`
  - `--color-ring` → `#808080`
  - `--color-sidebar` → `#f0ead8` (surface)
  - `--color-sidebar-foreground` → `#303030`
  - `--color-sidebar-primary` → `#303030`
  - `--color-sidebar-primary-foreground` → `#fdf6e3`
  - `--color-sidebar-accent` → `#e8e0cc`
  - `--color-sidebar-accent-foreground` → `#303030`
  - `--color-sidebar-border` → `#a8a8a8`
  - `--color-sidebar-ring` → `#808080`
- [x] Replace all oklch values in the `.dark { }` block with TeleClaude dark tokens:
  - `--color-background` → `#000000` (true black)
  - `--color-foreground` → `#d0d0d0` (text primary)
  - `--color-card` / `--color-popover` → `#262626` (surface)
  - `--color-card-foreground` / `--color-popover-foreground` → `#d0d0d0`
  - `--color-primary` → `#d0d0d0`
  - `--color-primary-foreground` → `#000000`
  - `--color-secondary` → `#303030` (panel)
  - `--color-secondary-foreground` → `#d0d0d0`
  - `--color-muted` → `#303030`
  - `--color-muted-foreground` → `#808080`
  - `--color-accent` → `#303030`
  - `--color-accent-foreground` → `#d0d0d0`
  - `--color-destructive` → `#ff5f5f` (status error)
  - `--color-destructive-foreground` → `#ff5f5f`
  - `--color-border` → `#585858`
  - `--color-input` → `#585858`
  - `--color-ring` → `#808080`
  - `--color-sidebar` → `#262626`
  - `--color-sidebar-foreground` → `#d0d0d0`
  - `--color-sidebar-primary` → `#d0d0d0`
  - `--color-sidebar-primary-foreground` → `#000000`
  - `--color-sidebar-accent` → `#303030`
  - `--color-sidebar-accent-foreground` → `#d0d0d0`
  - `--color-sidebar-border` → `#585858`
  - `--color-sidebar-ring` → `#808080`
- [x] Add user color CSS variables to the `@theme { }` block (same values for both modes):
  - `--user-bubble-bg: #e07030`
  - `--user-bubble-text: #ffffff`
- [x] Verify the base app renders with correct colors after replacement.

---

## Phase 2: Token System and CSS Variable Generation

### Task 2.1: Add user color tokens to tokens.ts

**File(s):** `frontend/lib/theme/tokens.ts`

- [x] Add a `USER_COLORS` export with `bubbleBg` (`#e07030`) and `bubbleText` (`#ffffff`).
- [x] These values are mode-independent (same orange in dark and light).

### Task 2.2: Extend CSS variable generation with user colors

**File(s):** `frontend/lib/theme/css-variables.ts`

- [ ] Add `--user-bubble-bg` and `--user-bubble-text` to the output of `generateCSSVariables()`.
- [ ] Verify the generated map includes all agent vars plus the new user vars.

---

## Phase 3: Theme Provider and CSS Variable Injection

### Task 3.1: Create unified ThemeProvider

**File(s):** `frontend/components/providers/ThemeProvider.tsx`

- [ ] Create a provider that wraps `next-themes` `ThemeProvider` (preserving `attribute="class"` for `.dark` toggling).
- [ ] On mount, call `injectCSSVariables(mode)` with the current resolved theme (dark/light).
- [ ] On theme change (dark/light switch), re-inject CSS variables for the new mode.
- [ ] Use `useTheme()` from `next-themes` to detect the resolved theme and react to changes.

### Task 3.2: Load theme.local.css override

**File(s):** `frontend/app/layout.tsx`

- [ ] Add a `<link rel="stylesheet" href="/theme.local.css" />` after the main stylesheet in the `<head>`.
- [ ] This loads the override file from `frontend/public/theme.local.css`.

### Task 3.3: Create theme.local.css default file

**File(s):** `frontend/public/theme.local.css`

- [ ] Create the file with all CSS custom property defaults as comments, showing operators what can be overridden:
  ```css
  /* TeleClaude theme overrides — edit values, refresh browser. No rebuild needed. */
  /* Uncomment and modify any variable to customize. */
  :root {
    /* --user-bubble-bg: #e07030; */
    /* --user-bubble-text: #ffffff; */
    /* --agent-claude-normal: #d7af87; */
    /* ... etc */
  }
  ```
- [ ] Add `theme.local.css` to `.gitignore` (the default ships but local edits should not be committed).

### Task 3.4: Wire ThemeProvider into layout

**File(s):** `frontend/app/layout.tsx`

- [ ] Replace the existing `next-themes` ThemeProvider with the new unified `ThemeProvider` from Task 3.1.
- [ ] Ensure dark/light toggle continues to function.

---

## Phase 4: Theming State (Peaceful vs Themed)

### Task 4.1: Create AgentTheming context

**File(s):** `frontend/hooks/useAgentTheming.ts`

- [ ] Create a React context that exposes `{ isThemed: boolean, setThemed: (on: boolean) => void }`.
- [ ] Default to `false` (peaceful mode).
- [ ] On mount, read the daemon API settings (`pane_theming_mode`) and derive:
  - `"off"` → `false`
  - `"agent_plus"` (or any other value) → `true`
- [ ] On change, persist to daemon API via settings PATCH (`pane_theming_mode: isThemed ? "agent_plus" : "off"`).

### Task 4.2: Create useAgentColors hook

**File(s):** `frontend/hooks/useAgentColors.ts`

- [ ] Create a hook `useAgentColors(agent: string)` that returns resolved CSS variable references.
- [ ] When `isThemed` is true: return agent-specific var references (`var(--agent-{agent}-subtle)` etc.).
- [ ] When `isThemed` is false: return peaceful neutral var references (`var(--peaceful-subtle)` etc.).
- [ ] Also expose user bubble vars: when themed, `var(--user-bubble-bg)` / `var(--user-bubble-text)`; when peaceful, neutral surface/text vars.

### Task 4.3: Add AgentTheming provider to layout

**File(s):** `frontend/app/layout.tsx` or `frontend/components/providers/ThemeProvider.tsx`

- [ ] Wrap the app with the `AgentTheming` provider inside the `ThemeProvider`.

---

## Phase 5: Theming Toggle UI

### Task 5.1: Add theming toggle

**File(s):** `frontend/components/` (header or settings area — determine exact location during build)

- [ ] Add a simple toggle switch (shadcn/ui Switch component or similar).
- [ ] Label: reflects peaceful vs themed state.
- [ ] Wired to `useAgentTheming().setThemed()`.
- [ ] Placed alongside or near the existing dark/light mode toggle.

---

## Phase 6: Apply Colors to Components

### Task 6.1: User bubble styling

**File(s):** `frontend/components/assistant/ThreadView.tsx` (or wherever `UserMessage` is defined)

- [ ] When `isThemed`: apply `var(--user-bubble-bg)` as background, `var(--user-bubble-text)` as text color.
- [ ] When peaceful: apply neutral gray background (`bg-muted` or `var(--color-secondary)`), structural text color.
- [ ] Remove any hardcoded `bg-primary` usage for user bubbles — replace with conditional CSS var references.

### Task 6.2: Assistant bubble styling

**File(s):** `frontend/components/assistant/ThreadView.tsx` (or wherever `AssistantMessage` is defined)

- [ ] When `isThemed`: apply agent-tinted background using the active session's agent type. Use `var(--agent-{agent}-subtle)` or `blendColors()` for the tint.
- [ ] When peaceful: apply neutral surface background (`bg-muted` / `var(--color-card)`).
- [ ] The active agent type comes from the session context (see Task 7.1).

### Task 6.3: Sidebar session item styling

**File(s):** `frontend/components/sidebar/` (determine exact file during build — likely `SessionItem.tsx` or similar)

- [ ] When `isThemed`: session item text uses `var(--agent-{agent}-normal)` based on each session's agent type.
- [ ] When peaceful: session item text uses default foreground color.

---

## Phase 7: Active Agent Context

### Task 7.1: Pass agent type to thread view

**File(s):** `frontend/components/assistant/ThreadView.tsx`, parent components

- [ ] The chat view already knows which session is active via session state.
- [ ] Extract the `active_agent` field from the session info.
- [ ] Pass it to message components so `AssistantMessage` can resolve the correct agent color tier.
- [ ] Ensure the agent type defaults gracefully when unknown (fall back to `claude` or peaceful neutral).

---

## Phase 8: Validation

### Task 8.1: Visual matrix verification

- [ ] Verify all 4 combinations render correctly:
  - Dark + Peaceful: black bg, neutral gray bubbles, neutral sidebar
  - Dark + Themed: black bg, agent-tinted assistant bubbles, orange user bubbles, agent sidebar
  - Light + Peaceful: warm paper bg, neutral cream bubbles, neutral sidebar
  - Light + Themed: warm paper bg, agent-tinted assistant bubbles, orange user bubbles, agent sidebar
- [ ] Verify chat area background is never agent-tinted in any combination.
- [ ] Verify `theme.local.css` overrides take effect (change `--user-bubble-bg`, refresh, observe).

### Task 8.2: Component smoke test

- [ ] All shadcn/ui components (buttons, dialogs, popovers, inputs) render correctly with hex values.
- [ ] Dark/light toggle works without delay or flash.
- [ ] Theming toggle persists across page reload.

### Task 8.3: Quality checks

- [ ] No hex values hardcoded in React components.
- [ ] `theme.local.css` is gitignored.
- [ ] `make lint` passes (or frontend equivalent lint/type check).
- [ ] No unchecked implementation tasks remain.

---

## Phase 9: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
