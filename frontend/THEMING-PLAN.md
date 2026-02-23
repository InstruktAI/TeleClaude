# Frontend Theming Plan — TUI Color Parity

## Status: FINAL SPEC — Ready for implementation

---

## 1. What already exists

### TUI (Python — source of truth)

- **File:** `teleclaude/cli/tui/theme.py`
- 3 agents: `claude`, `gemini`, `codex`
- 4 color tiers per agent: `subtle`, `muted`, `normal`, `highlight`
- Dark/light mode variants for all colors
- 5 pane theming modes: `off`(0), `highlight`(1), `highlight2`(2), `agent`(3), `agent_plus`(4)
- `resolve_style()` / `resolve_color()` — at levels 0,2 → peaceful (neutral grays); at levels 1,3,4 → agent colors
- `blend_colors(base, agent, pct)` for background hazes
- Peaceful mode: neutral grays (no agent tint)
- Background blend percentages (haze): inactive=12-18%, selected=8-12%

### Frontend (TypeScript — already ported)

- **`frontend/lib/theme/tokens.ts`** — ALL agent colors, theme tokens, blend function, ALREADY ported
  - `AGENT_COLORS[mode][agent]` → `{ subtle, muted, normal, highlight, haze }`
  - `THEME_TOKENS[mode]` → full structural token set (bg, text, border, selection, status, peaceful)
  - `blendColors()`, `hexToRgb()`, `rgbToHex()`, `detectThemeMode()`
  - `HAZE_CONFIG` with all blend percentages
- **`frontend/lib/theme/css-variables.ts`** — generates `--agent-claude-normal`, `--bg-base`, `--peaceful-normal`, etc. as CSS custom properties
  - `generateCSSVariables(mode)` → flat map of all CSS vars
  - `injectCSSVariables(mode)` → writes to `document.documentElement.style`
  - `clearCSSVariables()` → removes all
- **`frontend/lib/theme/ink-colors.ts`** — chalk-based terminal colors (for Ink TUI, not web)
- **`frontend/lib/animation/palettes.ts`** — animation palettes using tokens

### Current Next.js state

- **`frontend/app/globals.css`** — shadcn/ui default oklch color system for Tailwind
  - `@theme { ... }` light vars + `.dark { ... }` dark vars
  - These are the standard shadcn tokens: `--color-background`, `--color-foreground`, `--color-primary`, etc.
- **`frontend/app/layout.tsx`** — `next-themes` ThemeProvider with `attribute="class"` for `.dark` toggling
- **`frontend/lib/api/types.ts`** — `PaneThemingMode` type already defined
- **`frontend/lib/api/types.ts`** — `Settings.pane_theming_mode` and `SettingsPatch.pane_theming_mode` already typed

---

## 2. Two theming states

| State   | Name     | Description                                                                                        |
| ------- | -------- | -------------------------------------------------------------------------------------------------- |
| **off** | Peaceful | Grayscale only. User bubbles = neutral gray. Assistant bubbles = neutral gray. Sidebar = neutral.  |
| **on**  | Themed   | User bubbles = orange with white text. Assistant bubbles = agent-colored. Sidebar = agent-colored. |

Crossed with dark/light mode = 4 visual combinations.

### The matrix

|                     | Dark + Peaceful        | Dark + Themed                     | Light + Peaceful       | Light + Themed                    |
| ------------------- | ---------------------- | --------------------------------- | ---------------------- | --------------------------------- |
| Chat bg             | `#000000` (dark base)  | `#000000` (dark base)             | `#fdf6e3` (warm paper) | `#fdf6e3` (warm paper)            |
| Assistant bubble bg | neutral `#262626`      | agent-tinted (e.g. claude subtle) | neutral `#f0ead8`      | agent-tinted (e.g. claude subtle) |
| Assistant text      | `#d0d0d0`              | `#d0d0d0`                         | `#303030`              | `#303030`                         |
| User bubble bg      | neutral gray `#444444` | **orange** `#e07030`              | neutral gray `#d0d0d0` | **orange** `#e07030`              |
| User text           | `#e4e4e4` (light gray) | **`#ffffff`** (white on orange)   | `#303030` (near-black) | **`#ffffff`** (white on orange)   |
| Sidebar items       | gray text              | agent-colored text                | gray text              | agent-colored text                |

### Rules

- **Chat area background** — NEVER agent-tinted. Always follows dark/light theme only.
- **User bubbles in peaceful mode** — neutral grays from structural token palette (not pure black/white).
- **User bubbles in themed mode** — orange background, white text. Same orange in both dark and light mode.
- **Assistant bubbles in themed mode** — agent-colored (per active session's agent).

---

## 3. Color reference

### User color (new)

| Token                | Value     | Notes                                   |
| -------------------- | --------- | --------------------------------------- |
| `--user-bubble-bg`   | `#e07030` | Orange — warm, distinct from all agents |
| `--user-bubble-text` | `#ffffff` | White text on orange, both modes        |

### Agent colors — Dark mode

| Agent  | Subtle    | Muted     | Normal    | Highlight | Haze      |
| ------ | --------- | --------- | --------- | --------- | --------- |
| Claude | `#875f00` | `#af875f` | `#d7af87` | `#ffffff` | `#af875f` |
| Gemini | `#8787af` | `#af87ff` | `#d7afff` | `#ffffff` | `#af87ff` |
| Codex  | `#5f87af` | `#87afd7` | `#afd7ff` | `#ffffff` | `#87afaf` |

### Agent colors — Light mode

| Agent  | Subtle    | Muted     | Normal    | Highlight | Haze      |
| ------ | --------- | --------- | --------- | --------- | --------- |
| Claude | `#d7af87` | `#af875f` | `#875f00` | `#000000` | `#af875f` |
| Gemini | `#d787ff` | `#af5fff` | `#870087` | `#000000` | `#af5fff` |
| Codex  | `#87afd7` | `#5f87af` | `#005f87` | `#000000` | `#5f8787` |

### Neutral/Peaceful colors

| Tier      | Dark      | Light     |
| --------- | --------- | --------- |
| highlight | `#e0e0e0` | `#202020` |
| normal    | `#a0a0a0` | `#606060` |
| muted     | `#707070` | `#909090` |
| subtle    | `#484848` | `#b8b8b8` |

### Structural tokens (dark)

- Background base: `#000000`
- Surface: `#262626`
- Panel: `#303030`
- Text primary: `#d0d0d0` (soft light gray)
- Text secondary: `#bcbcbc`
- Text muted: `#808080`
- Border: `#585858`
- Status: active=`#5faf5f`, error=`#ff5f5f`, warning=`#d7af00`

### Structural tokens (light)

- Background base: `#fdf6e3` (warm paper)
- Surface: `#f0ead8`
- Panel: `#e8e0cc`
- Text primary: `#303030` (near-black)
- Text secondary: `#444444`
- Text muted: `#808080`
- Border: `#a8a8a8`
- Status: active=`#008700`, error=`#d70000`, warning=`#af8700`

---

## 4. Implementation plan

### Step 1: Replace shadcn oklch with TeleClaude tokens in globals.css

- Replace the generic oklch values in `@theme { }` and `.dark { }` with TeleClaude structural tokens
- Map shadcn semantic variables → TeleClaude tokens:
  - `--color-background` → `THEME_TOKENS.bg.base`
  - `--color-foreground` → `THEME_TOKENS.text.primary`
  - `--color-card` / `--color-popover` → `THEME_TOKENS.bg.surface`
  - `--color-muted` → token-based neutral
  - `--color-border` → `THEME_TOKENS.border.default`
  - `--color-destructive` → `THEME_TOKENS.status.error`
  - etc.
- This ensures the base theme matches the TUI's neutral look
- Add `--user-bubble-bg` and `--user-bubble-text` as CSS vars (orange + white defaults)

### Step 2: Add agent + user CSS variables

- Inject `--agent-{name}-{tier}`, `--agent-{name}-haze`, `--user-bubble-bg`, `--user-bubble-text` as CSS custom properties
- Extend `css-variables.ts` to include user color vars
- Create a React context/provider that calls `injectCSSVariables()` on mount and on theme change
- Wire to `next-themes` so mode switches trigger re-injection

### Step 3: Create theme override file (`theme.local.css`)

- App loads an optional `theme.local.css` override file at runtime
- Loaded via `<link>` tag after the main stylesheet — CSS cascade ensures overrides win
- Gitignored via `.local` convention
- Contains CSS custom property overrides:
  ```css
  :root {
    --user-bubble-bg: #e07030;
    --user-bubble-text: #ffffff;
    --agent-claude-normal: #d7af87;
    /* override anything */
  }
  ```
- Default file ships with the repo (all defaults). Operators edit to customize.
- No rebuild needed — edit the file, refresh the browser.
- Future: admin UI that writes to this file from within the platform.

### Step 4: Create theming state management

- Create an `AgentTheming` context: boolean on/off (peaceful vs themed)
- Persist preference via daemon API (`pane_theming_mode` setting already exists)
- Map: off → `"off"`, on → `"agent_plus"`

### Step 5: Create theming toggle UI

- Simple on/off toggle in the header or settings area
- When off: all neutral grayscale. When on: agent + user colors appear.

### Step 6: Apply colors conditionally

- **Peaceful (off):**
  - Assistant bubbles: neutral bg (`bg-muted` / surface color)
  - User bubbles: neutral gray bg, structural text color
  - Sidebar: neutral gray text
- **Themed (on):**
  - Assistant bubbles: agent-tinted background (agent subtle or blended haze)
  - User bubbles: `var(--user-bubble-bg)` background, `var(--user-bubble-text)` text
  - Sidebar session items: agent-colored text using `var(--agent-{name}-normal)`
  - Chat area background: unchanged — always theme bg, never agent-tinted

### Step 7: Wire active agent context

- The chat view knows which session is active → `SessionInfo.active_agent`
- Pass the active agent down to the thread view
- `AssistantMessage` reads agent + theming on/off to decide bubble bg
- `UserMessage` reads theming on/off to decide between neutral gray and orange

---

## 5. Key architectural decisions

1. **CSS variables everywhere.** All colors — agent, user, structural — are CSS custom properties. Components reference `var(--user-bubble-bg)` etc. Never hardcode hex in components.

2. **`theme.local.css` for white-labeling.** A single CSS override file that operators can edit without rebuilding. Loaded at runtime via `<link>` after the main stylesheet. Gitignored. Deployable via file mount. Future: editable from admin UI.

3. **Dual-layer theming.** `next-themes` handles dark/light. A boolean context handles peaceful/themed. They're orthogonal — dark + themed = dark background + agent-colored assistant bubbles + orange user bubbles.

4. **Base theme uses TeleClaude tokens, not shadcn defaults.** Replace oklch values in globals.css with our hex values from `THEME_TOKENS`. Warm paper light bg, true black dark bg — matching the TUI.

5. **Blend at render time for assistant bubbles only.** Assistant bubble backgrounds use `blendColors()` from tokens.ts. Chat background is NEVER blended. User bubbles use a flat color (orange).

6. **No rebuild for color changes.** All customization flows through CSS variables. The `theme.local.css` file, runtime injection via `injectCSSVariables()`, and the Tailwind `var()` references make the entire color system dynamic without touching the build.

---

## 6. Files to create/modify

| File                                                          | Action     | Purpose                                                       |
| ------------------------------------------------------------- | ---------- | ------------------------------------------------------------- |
| `frontend/app/globals.css`                                    | **Modify** | Replace oklch with TeleClaude tokens, add user color vars     |
| `frontend/public/theme.local.css`                             | **Create** | Default override file (all defaults, gitignored)              |
| `frontend/lib/theme/css-variables.ts`                         | **Modify** | Add user color vars to generation                             |
| `frontend/lib/theme/tokens.ts`                                | **Modify** | Add user color tokens                                         |
| `frontend/components/providers/ThemeProvider.tsx`             | **Create** | next-themes + CSS var injection + theming on/off context      |
| `frontend/hooks/useAgentTheming.ts`                           | **Create** | Hook to read/set peaceful vs themed                           |
| `frontend/hooks/useAgentColors.ts`                            | **Create** | Hook returning resolved colors for an agent (respects on/off) |
| `frontend/app/layout.tsx`                                     | **Modify** | Use new ThemeProvider, load theme.local.css                   |
| `frontend/components/assistant/ThreadView.tsx`                | **Modify** | Bubble colors from CSS vars, conditional on theming state     |
| `frontend/components/sidebar/SessionItem.tsx` (or equivalent) | **Modify** | Agent-colored text when themed                                |

---

## 7. Dependencies

- `next-themes` — already installed
- `frontend/lib/theme/tokens.ts` — already has all color data
- `frontend/lib/theme/css-variables.ts` — already generates CSS vars
- No new npm packages needed

---

## 8. Deployment approach

- **No Docker.** Run from the repo: `next build && next start` on one machine.
- **Color customization:** Edit `frontend/public/theme.local.css`, refresh browser. No rebuild.
- **HTTPS:** Defer. When needed: Caddy reverse proxy or mkcert for local network certs.
- **Future admin UI:** An admin page that writes color values to `theme.local.css` on the server. The file mount preserves state across restarts.

---

## 9. Related TUI bug filed

**Bug:** `fix-agent-theme-primary-secondary-set-to-cla`
**Worktree:** `trees/fix-agent-theme-primary-secondary-set-to-cla`

The Textual theme `primary`/`secondary` fields in the agent variants are set to Claude's brown.
No TUI widget explicitly references `$primary`/`$secondary`, but Textual's built-in default
styles for active/focus/hover states do — causing brown bleed on double-click for all agents.

Fix: (1) Replace with neutral grays. (2) Eliminate all implicit Textual active/focus/hover/double-click
states in TCSS — we have our own tree navigation and selection UX. No Textual default interaction styling should ever be visible.

---

## 10. What NOT to do

- Don't add Tailwind color extensions via `tailwind.config` — use CSS vars at runtime
- Don't hardcode hex values in components — always reference CSS vars
- Don't color the chat area background — it always follows dark/light only
- Don't break the existing dark/light toggle — theming state is additive
- Don't touch `ink-colors.ts` — that's for the Ink TUI, not web
- Don't containerize — run from disk
- Don't rebuild for color changes — everything is runtime CSS vars + override file
