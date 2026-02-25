# Demo: frontend-theming-tui-parity

## Validation

```bash
# Verify globals.css no longer contains oklch values
! grep -q "oklch" frontend/app/globals.css && echo "PASS: No oklch values in globals.css" || echo "FAIL: oklch values still present"
```

```bash
# Verify TeleClaude structural tokens are present
grep -q "#fdf6e3" frontend/app/globals.css && echo "PASS: Warm paper bg token present" || echo "FAIL: Missing warm paper token"
grep -q "#000000" frontend/app/globals.css && echo "PASS: True black bg token present" || echo "FAIL: Missing true black token"
```

```bash
# Verify user color tokens exist
grep -q "user-bubble-bg" frontend/app/globals.css && echo "PASS: User bubble bg var exists" || echo "FAIL: Missing user bubble bg var"
grep -q "#e07030" frontend/app/globals.css && echo "PASS: Orange user color present" || echo "FAIL: Missing orange user color"
```

```bash
# Verify theme.local.css exists in public
test -f frontend/public/theme.local.css && echo "PASS: theme.local.css exists" || echo "FAIL: Missing theme.local.css"
```

```bash
# Verify theme.local.css is gitignored
grep -q "theme.local.css" frontend/.gitignore 2>/dev/null || grep -q "theme.local.css" .gitignore 2>/dev/null && echo "PASS: theme.local.css is gitignored" || echo "FAIL: theme.local.css not gitignored"
```

```bash
# Verify no hardcoded hex values in React components (excluding CSS and token files)
FOUND=$(grep -rn '#[0-9a-fA-F]\{6\}' frontend/components/ --include='*.tsx' --include='*.ts' 2>/dev/null | grep -v '\.css' | grep -v 'tokens\.ts' | grep -v 'css-variables\.ts' | grep -v 'ink-colors\.ts' || true)
if [ -z "$FOUND" ]; then echo "PASS: No hardcoded hex in components"; else echo "FAIL: Hardcoded hex found:"; echo "$FOUND"; fi
```

```bash
# Verify ThemeProvider exists
test -f frontend/components/providers/ThemeProvider.tsx && echo "PASS: ThemeProvider exists" || echo "FAIL: Missing ThemeProvider"
```

```bash
# Verify theming hooks exist
test -f frontend/hooks/useAgentTheming.ts && echo "PASS: useAgentTheming hook exists" || echo "FAIL: Missing useAgentTheming"
test -f frontend/hooks/useAgentColors.ts && echo "PASS: useAgentColors hook exists" || echo "FAIL: Missing useAgentColors"
```

## Guided Presentation

### Act 1: The Foundation

Open the frontend in a browser. Toggle between dark and light mode. Observe the base colors:

- **Dark mode:** True black background (`#000000`), warm gray surfaces (`#262626`), soft gray text (`#d0d0d0`). This matches the TUI exactly.
- **Light mode:** Warm paper background (`#fdf6e3`), cream surfaces (`#f0ead8`), near-black text (`#303030`). The same warm palette as the TUI.

The shadcn/ui components (buttons, inputs, dialogs) all render using our structural tokens. No trace of the generic oklch defaults.

### Act 2: Peaceful Mode

Ensure the theming toggle is off (peaceful mode). Send a message and observe:

- **User bubbles** are neutral gray — they blend into the theme without drawing attention.
- **Assistant bubbles** are neutral surface color — indistinguishable from the background card color.
- **Sidebar** session items are plain gray text — no agent color anywhere.

This is the base state. Clean, calm, professional. No visual noise.

### Act 3: The Reveal

Toggle theming on. The interface comes alive:

- **User bubbles** turn orange (`#e07030`) with crisp white text. Warm, distinctive, unmistakably "you."
- **Assistant bubbles** take on the active agent's color. Claude sessions show warm brown tints. Gemini sessions show purple. Codex sessions show blue.
- **Sidebar** session labels color-code by agent type. At a glance, you see which sessions belong to which agent.

The chat area background stays unchanged. Dark or light, the background never picks up agent color. The bubbles float on a neutral stage.

### Act 4: The Matrix

Walk through all four combinations:

1. **Dark + Peaceful** — Black canvas, gray everything. Minimal.
2. **Dark + Themed** — Black canvas, colored bubbles pop against the dark. Orange user bubbles glow.
3. **Light + Peaceful** — Warm paper, cream and gray. Serene.
4. **Light + Themed** — Warm paper, agent tints are softer in light mode. Orange stays bold.

### Act 5: White-Labeling

Open `frontend/public/theme.local.css`. Uncomment a line and change the user bubble color:

```css
:root {
  --user-bubble-bg: #4488ff;
}
```

Refresh the browser. User bubbles are now blue. No rebuild. No restart. Just CSS.

This is the customization story. An operator deploys TeleClaude, edits one file, and the brand is theirs.
