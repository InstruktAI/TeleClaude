# Input: frontend-theming-tui-parity

Port the TUI's agent color theming system to the Next.js web frontend. The TUI (`teleclaude/cli/tui/theme.py`) is the source of truth for all agent colors, structural tokens, and theming modes. The frontend already has the token data ported to TypeScript (`frontend/lib/theme/tokens.ts`, `frontend/lib/theme/css-variables.ts`), but the web UI still uses shadcn/ui's generic oklch defaults instead of TeleClaude's colors.

Two theming states: **peaceful** (neutral grayscale) and **themed** (agent-colored assistant bubbles, orange user bubbles, agent-colored sidebar). Crossed with dark/light mode = 4 visual combinations. The chat area background never gets agent color — it always follows dark/light only.

User bubbles in themed mode use orange (`#e07030`) with white text — a warm, distinctive accent that stands apart from all agent palettes.

All colors must flow through CSS custom properties. A `theme.local.css` override file enables white-labeling without rebuilds — edit the file, refresh the browser.

Reference spec: `frontend/THEMING-PLAN.md`
