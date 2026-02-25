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

### Frontend (TypeScript Logic Layer)

- **`frontend/lib/theme/tokens.ts`** — Holds logic-level hex values for non-CSS contexts.
  - Maintains a synced copy of tokens for:
    - Canvas animations (blending, interpolation)
    - CLI / Terminal rendering (Ink)
  - Provides types: `AgentType`, `ThemeMode`, `ThemeTokens`, etc.
  - Utility functions: `blendColors()`, `hexToRgb()`, `detectThemeMode()`

---

## 2. Two theming states

| State   | Name     | Description                                                                                        |
| ------- | -------- | -------------------------------------------------------------------------------------------------- |
| **off** | Peaceful | Grayscale only. User bubbles = neutral gray. Assistant bubbles = neutral gray. Sidebar = neutral.  |
| **on**  | Themed   | User bubbles = orange with white text. Assistant bubbles = agent-colored. Sidebar = agent-colored. |

Crossed with dark/light mode = 4 visual combinations.

---

## 3. Implementation plan (CSS Design Token Manifest)

### Step 1: Centralize Tokens in CSS

- `lib/theme/tokens.css` is the **absolute source of truth** for all hex codes.
- Edit this file to get full IDE support (color pickers, auto-completion).
- It contains both `:root` (light) and `.dark` blocks using the `--tc-` prefix.

### Step 2: Integrated CSS Pipeline

- `app/globals.css` `@import`s `lib/theme/tokens.css`.
- Standard Tailwind variables (e.g., `--color-background`) are mapped to the `--tc-` proxy variables in the `@theme` block.
- This ensures zero-flash transitions and instant dark mode support via standard CSS cascade.

### Step 3: Logic Synchronization

- `lib/theme/tokens.ts` maintains a logic-level copy of the hex codes for special use cases:
  - **Canvas Animations:** Requires hex parsing for color blending.
  - **CLI (Ink):** Requires hex values for terminal color codes.
- `hooks/useAgentColors.ts` and React components use the `var(--tc-...)` variables directly, ensuring they respond to CSS changes immediately without a JS rebuild.

### Step 4: Local Preference Management

- `AgentTheming` context handles the peaceful/themed toggle.
- Preferences are stored strictly in browser `localStorage`, keeping the daemon API business-agnostic.

---

## 4. Message cleaning and command formatting

To maintain a clean chat experience, the frontend implements a robust text cleaning pipeline (`lib/utils/text.ts`):

1. **Python Wrapper Cleaning:** Extracts raw text from legacy stringified Python lists (`[{'text': '...'}]`) found in historical messages or stream fragments.
2. **System Content Filtering:** Discards internal system messages like `[TeleClaude Checkpoint]`, `<task-notification>`, etc.
3. **Command Reformatting:** Intercepts messages starting with `<command-message>`.
   - Extracts `<command-name>` and `<command-args>`.
   - Replaces the entire message body with a clean string: `/command args`.
   - **Burst suppression:** If a command header is detected, all subsequent technical "body" messages in the same same-role burst are discarded.

---

## 5. Key architectural decisions

1. **CSS as Visual Source of Truth:** Move hex codes to `tokens.css` to enable native IDE color support.
2. **Proxy Variable Mapping:** Use `--tc-` prefixed variables to decouple design tokens from Tailwind's internal naming.
3. **Static Import:** Use CSS `@import` instead of runtime JS injection for maximum performance and reliability.
4. **Local-Only Preferences:** Keep UI-specific toggles in the browser to avoid unnecessary backend state.

---

## 6. Files to create/modify

| File                                           | Action     | Purpose                                                   |
| ---------------------------------------------- | ---------- | --------------------------------------------------------- |
| `frontend/lib/theme/tokens.css`                | **Create** | **Absolute source of truth** for all hex codes            |
| `frontend/app/globals.css`                     | **Modify** | `@import` tokens and map Tailwind to proxy variables      |
| `frontend/lib/theme/tokens.ts`                 | **Modify** | Logic-level tokens for non-CSS contexts (Animations, CLI) |
| `frontend/hooks/useAgentColors.ts`             | **Modify** | Use `--tc-` proxy variables for dynamic web styling       |
| `frontend/components/parts/DarkModeToggle.tsx` | **Modify** | Robust Sun/Moon/Monitor cycle for theme management        |
| `frontend/hooks/useAgentTheming.tsx`           | **Modify** | Local-only persistence for peaceful vs themed             |
| `frontend/lib/utils/text.ts`                   | **Create** | Centralized cleaning and command formatting logic         |
| `frontend/app/layout.tsx`                      | **Modify** | Simplified layout (removed redundant runtime injection)   |
