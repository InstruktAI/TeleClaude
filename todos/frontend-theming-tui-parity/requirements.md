# Requirements: frontend-theming-tui-parity

## Goal

Replace the Next.js frontend's generic shadcn/ui color system with TeleClaude's own token palette, then implement a two-state theming system (peaceful vs themed) that gives assistant bubbles agent-specific colors, user bubbles a distinctive orange accent, and the sidebar agent-colored session labels — all controlled by a single toggle and fully customizable via CSS variables at runtime.

## In scope

1. **Base theme replacement** — Replace all oklch values in `globals.css` with TeleClaude structural token hex values from `THEME_TOKENS` (dark: true black base, warm grays; light: warm paper base `#fdf6e3`).
2. **User color tokens** — Add `--user-bubble-bg` (`#e07030`) and `--user-bubble-text` (`#ffffff`) to the token system and CSS variable generation.
3. **CSS variable injection** — Extend `css-variables.ts` to include user color vars. Create a React provider that injects all CSS variables on mount and on dark/light mode change via `next-themes`.
4. **Theme override file** — Create `frontend/public/theme.local.css` with all CSS variable defaults. Loaded via `<link>` tag after the main stylesheet so CSS cascade ensures overrides win. Gitignored via `.local` convention.
5. **Theming state management** — Boolean on/off context (peaceful vs themed). Persisted via daemon API using the existing `pane_theming_mode` setting. Map: off = `"off"`, on = `"agent_plus"`.
6. **Theming toggle** — Simple on/off toggle in the header or settings area.
7. **Conditional color application** — Assistant bubbles, user bubbles, and sidebar items switch between neutral and colored based on theming state. Chat area background never receives agent color.
8. **Active agent wiring** — Thread view reads the active session's agent type to resolve the correct agent color tier for assistant bubbles.

## Out of scope

- Ink TUI colors (`ink-colors.ts`) — terminal only, not web.
- Tailwind config color extensions — all colors use runtime CSS vars.
- Docker containerization — run from disk.
- HTTPS setup — deferred; Caddy or mkcert when needed.
- Admin UI for editing `theme.local.css` — future work.
- TUI `$primary`/`$secondary` Textual theme bug — separate todo (`fix-agent-theme-primary-secondary-set-to-cla`).

## Success Criteria

- [ ] SC-1: `globals.css` uses TeleClaude hex tokens, not oklch. Dark mode = `#000000` base, `#262626` surface. Light mode = `#fdf6e3` base, `#f0ead8` surface.
- [ ] SC-2: All agent color tiers (`subtle`, `muted`, `normal`, `highlight`, `haze`) and user color tokens (`--user-bubble-bg`, `--user-bubble-text`) are available as CSS custom properties.
- [ ] SC-3: `theme.local.css` exists in `frontend/public/`, is loaded after the main stylesheet, and CSS variable overrides in it take effect without rebuild.
- [ ] SC-4: A theming toggle switches between peaceful (neutral) and themed (colored) modes. The preference persists across page reloads via the daemon API.
- [ ] SC-5: In **peaceful mode**: assistant bubbles use neutral surface bg, user bubbles use neutral gray bg, sidebar uses neutral gray text. No agent colors visible.
- [ ] SC-6: In **themed mode**: assistant bubbles use agent-tinted bg (per active session's agent), user bubbles use orange bg (`#e07030`) with white text (`#ffffff`), sidebar session items use agent-colored text.
- [ ] SC-7: Chat area background follows dark/light mode only — never agent-tinted, in any theming state.
- [ ] SC-8: Dark/light mode toggle continues to work. CSS variables re-inject on mode switch.
- [ ] SC-9: No hex values hardcoded in React components — all color references use CSS variables or Tailwind utility classes backed by CSS variables.
- [ ] SC-10: The 4-combination matrix (dark+peaceful, dark+themed, light+peaceful, light+themed) renders correctly with the colors specified in `THEMING-PLAN.md` section 2.

## Constraints

- All colors flow through CSS custom properties. Components reference `var(--user-bubble-bg)` etc. Never hardcode hex in components.
- `theme.local.css` is the white-labeling mechanism. No rebuild for color changes.
- `next-themes` handles dark/light. The theming boolean handles peaceful/themed. They are orthogonal.
- Base theme uses TeleClaude token hex values, not shadcn oklch defaults.
- Blend at render time for assistant bubbles only. Chat background is never blended. User bubbles use a flat orange.
- Do not touch `ink-colors.ts` — that's for the Ink TUI.
- Do not add Tailwind color extensions via config — use runtime CSS vars.

## Risks

- Replacing oklch values with hex in `globals.css` may break shadcn/ui component styles if any component assumes the oklch color space for relative color operations. Mitigation: test all shadcn components after replacement.
- The `@theme { }` block in Tailwind CSS v4 registers CSS variables at the `@property` level. Switching from oklch to hex changes the color space. Verify Tailwind's `bg-background`, `text-foreground` etc. still resolve correctly.
- `theme.local.css` is public and unauthenticated. It contains only cosmetic CSS variables, not secrets. Acceptable risk.
- The `pane_theming_mode` API setting maps 5 TUI levels to 2 web states. The web frontend only uses `"off"` and `"agent_plus"`. Other values should map to the nearest web state gracefully.
