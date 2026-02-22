# Frontend Theming Plan — TUI Color Parity

## Status: RESEARCH COMPLETE — Ready for implementation

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

## 2. The 2 frontend theming states

Two states, crossed with dark/light mode = 4 visual combinations.

| State   | Name     | What gets colored                                                                                                                                                | TUI equivalent         |
| ------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| **off** | Peaceful | Nothing agent-specific. Pure grayscale. Sidebar neutral, chat neutral.                                                                                           | `off` (level 0)        |
| **on**  | Agent    | Assistant message bubbles use agent colors. Chat background stays theme-only (dark or light). User bubbles stay neutral. Sidebar session items use agent colors. | `agent_plus` (level 4) |

### What is NOT colored (ever)

- **Chat area background** — always follows dark/light theme only. No agent haze on the chat canvas.
- **User message bubbles** — always neutral (primary foreground on primary background).

### What IS colored (when agent theming is on)

- **Assistant message bubbles** — background tinted with agent color (e.g., subtle agent haze or agent muted bg).
- **Sidebar session items** — agent-colored text or subtle background tint to identify which agent is active.

### The matrix

|                     | Dark + Off            | Dark + On                                   | Light + Off            | Light + On                                  |
| ------------------- | --------------------- | ------------------------------------------- | ---------------------- | ------------------------------------------- |
| Chat bg             | `#000000` (dark base) | `#000000` (dark base)                       | `#fdf6e3` (warm paper) | `#fdf6e3` (warm paper)                      |
| Assistant bubble bg | neutral `#262626`     | agent-tinted (e.g. claude `#875f00` subtle) | neutral `#f0ead8`      | agent-tinted (e.g. claude `#d7af87` subtle) |
| User bubble         | neutral               | neutral                                     | neutral                | neutral                                     |
| Sidebar items       | gray text             | agent-colored text                          | gray text              | agent-colored text                          |

---

## 3. Agent color reference (hex values)

### Dark mode

| Agent  | Subtle    | Muted     | Normal    | Highlight | Haze      |
| ------ | --------- | --------- | --------- | --------- | --------- |
| Claude | `#875f00` | `#af875f` | `#d7af87` | `#ffffff` | `#af875f` |
| Gemini | `#8787af` | `#af87ff` | `#d7afff` | `#ffffff` | `#af87ff` |
| Codex  | `#5f87af` | `#87afd7` | `#afd7ff` | `#ffffff` | `#87afaf` |

### Light mode

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
- Status active: `#5faf5f` (green), error: `#ff5f5f`, warning: `#d7af00`

### Structural tokens (light)

- Background base: `#fdf6e3` (warm paper)
- Surface: `#f0ead8`
- Panel: `#e8e0cc`
- Text primary: `#303030` (near-black)
- Text secondary: `#444444`
- Text muted: `#808080`
- Border: `#a8a8a8`
- Status active: `#008700`, error: `#d70000`, warning: `#af8700`

---

## 4. Implementation plan

### Step 1: Replace shadcn oklch with TeleClaude tokens in globals.css

- Replace the generic oklch values in `@theme { }` and `.dark { }` with the TeleClaude structural tokens from `THEME_TOKENS`
- Map shadcn semantic variables → TeleClaude tokens:
  - `--color-background` → `THEME_TOKENS.bg.base`
  - `--color-foreground` → `THEME_TOKENS.text.primary`
  - `--color-card` / `--color-popover` → `THEME_TOKENS.bg.surface`
  - `--color-muted` → token-based neutral
  - `--color-border` → `THEME_TOKENS.border.default`
  - `--color-destructive` → `THEME_TOKENS.status.error`
  - etc.
- This ensures the base theme (Peaceful/State 0) matches the TUI's neutral look

### Step 2: Add agent CSS variables

- Inject `--agent-{name}-{tier}` and `--agent-{name}-haze` as CSS custom properties
- Use `css-variables.ts` `injectCSSVariables()` — it already generates all of these
- Create a React context/provider that calls `injectCSSVariables()` on mount and on theme change
- Wire to `next-themes` so mode switches trigger re-injection

### Step 3: Create agent theming state management

- Create an `AgentTheming` context: boolean on/off
- Persist preference via daemon API (`pane_theming_mode` setting already exists)
- Map: off → `"off"`, on → `"agent_plus"`

### Step 4: Create theming toggle UI

- Simple on/off toggle in the header or settings area
- When off: all neutral. When on: agent colors appear on assistant bubbles and sidebar.

### Step 5: Apply agent colors conditionally

- **Off (Peaceful):** No agent-specific colors anywhere. Assistant bubbles use neutral bg (`bg-muted`). Sidebar items use neutral text.
- **On (Agent):**
  - Assistant message bubbles: agent-tinted background (e.g., `blendColors(themeBg, agentHaze, ~0.15)` or agent subtle as bg)
  - Sidebar session items: agent-colored text using `--agent-{name}-normal`
  - Chat area background: unchanged — always theme bg (dark or light), never agent-tinted
  - User message bubbles: unchanged — always neutral

### Step 6: Wire active agent context

- The chat view already knows which session is active → `SessionInfo.active_agent`
- Pass the active agent down to the thread view
- `AssistantMessage` component reads the agent + theming on/off to decide bubble bg color

---

## 5. Key architectural decisions

1. **CSS variables, not Tailwind config extensions.** The token system already generates CSS vars. We inject them at runtime and reference them via `var(--agent-claude-normal)` in className strings or inline styles. This avoids rebuilding Tailwind for each agent.

2. **Dual-layer theming.** `next-themes` handles dark/light. A simple boolean context handles agent coloring on/off. They're orthogonal — dark mode + agent on = dark agent-colored bubbles.

3. **Base theme uses TeleClaude tokens, not shadcn defaults.** Replace the oklch values in globals.css with our hex values from `THEME_TOKENS`. This gives us the warm paper background in light mode and the true black in dark mode — matching the TUI exactly.

4. **Blend at render time for bubbles only.** Assistant bubble backgrounds use `blendColors()` from tokens.ts at render time, producing inline style hex values. Chat area background is NEVER blended — it always uses the plain theme background.

---

## 6. Files to create/modify

| File                                                          | Action     | Purpose                                                             |
| ------------------------------------------------------------- | ---------- | ------------------------------------------------------------------- |
| `frontend/app/globals.css`                                    | **Modify** | Replace oklch values with TeleClaude token hex values               |
| `frontend/components/providers/ThemeProvider.tsx`             | **Create** | Wraps next-themes + injects CSS vars + agent theming on/off context |
| `frontend/hooks/useAgentTheming.ts`                           | **Create** | Hook to read/set agent theming on/off                               |
| `frontend/hooks/useAgentColors.ts`                            | **Create** | Hook that returns resolved colors for an agent (respects on/off)    |
| `frontend/app/layout.tsx`                                     | **Modify** | Use new ThemeProvider                                               |
| `frontend/components/assistant/ThreadView.tsx`                | **Modify** | Assistant bubble bg uses agent color when theming is on             |
| `frontend/components/sidebar/SessionItem.tsx` (or equivalent) | **Modify** | Session items use agent-colored text when theming is on             |

---

## 7. Dependencies

- `next-themes` — already installed
- `frontend/lib/theme/tokens.ts` — already has all color data
- `frontend/lib/theme/css-variables.ts` — already generates CSS vars
- No new npm packages needed

---

## 8. User message bubble colors

No primary accent color. User bubbles use the neutral structural gradient from the TUI tokens.
The user is visually "neutral" — the agent colors do the talking.

### Dark mode user bubbles

- Bubble background: neutral gray from `THEME_TOKENS.dark` — something in the `selection.base` (`#444444`) to `selection.surface` (`#4e4e4e`) range. Not white.
- Text: `text.primary` (`#e4e4e4`) — soft light gray, not pure white.

### Light mode user bubbles

- Bubble background: neutral gray from `THEME_TOKENS.light` — something in the `selection.base` (`#d0d0d0`) to `selection.surface` (`#c6c6c6`) range. Not black.
- Text: `text.primary` (`#303030`) — near-black, not pure black.

### Rationale

- Matches the TUI's neutral gradient philosophy (never pure black/white for surfaces)
- User bubbles stay achromatic in both theming states (off and on)
- Orange was considered as a user accent but deferred — the neutral approach works for now

---

## 9. Related TUI bug filed

**Bug:** `fix-agent-theme-primary-secondary-set-to-cla`
**Worktree:** `trees/fix-agent-theme-primary-secondary-set-to-cla`

The Textual theme `primary`/`secondary` fields in the agent variants are set to Claude's brown.
No TUI widget explicitly references `$primary`/`$secondary`, but Textual's built-in default
styles for active/focus/hover states do — causing brown bleed on double-click for all agents.

Fix: (1) Replace with neutral grays. (2) Eliminate all implicit Textual active/focus/hover/double-click
states in TCSS — we have our own tree navigation and selection UX.

---

## 10. What NOT to do

- Don't add Tailwind color extensions via `tailwind.config` — use CSS vars at runtime
- Don't create a separate color file — `tokens.ts` is the single source of truth
- Don't break the existing dark/light toggle — it stays as-is, theming level is additive
- Don't touch `ink-colors.ts` — that's for the Ink TUI, not the web frontend
- Don't color the chat area background with agent haze — it always follows dark/light only
- Don't use a primary accent color for user bubbles — keep them neutral/achromatic
