---
description: 'The TeleClaude frontend: a Next.js web app independent from the Python TUI — architecture boundary, build/run, theming, conventions.'
visibility: 'internal'
---

# Frontend — Design

## Purpose

`frontend/` is a **Next.js web application** — the browser UI for TeleClaude. It is
**not** a terminal UI and must not contain terminal, TUI, or Python-TUI concepts.

TeleClaude has two independent UIs with completely different architectures and **no
shared architecture between them**:

|           | Python TUI            | This Frontend               |
| --------- | --------------------- | --------------------------- |
| Location  | `teleclaude/cli/tui/` | `frontend/`                 |
| Framework | Python Textual + tmux | Next.js + React             |
| Runs in   | Terminal              | Browser                     |
| State     | Dataclass + reducer   | React state / server state  |
| Layout    | Tmux pane splits      | CSS / responsive web layout |

The Python TUI solves terminal constraints that do not exist in a browser. When
building a frontend feature, design the web UX from scratch using web-native patterns;
never port from the Python TUI.

## Inputs/Outputs

The frontend never talks to external services directly — it proxies everything to the
TeleClaude daemon (reachable via `/tmp/teleclaude-api.sock`):

- **SSE streaming:** `app/api/chat/route.ts` transforms the daemon stream into an AI
  SDK-compatible format.
- **WebSocket bridge:** `server.ts` handles auth-guarded WebSocket upgrades for
  real-time session-tree updates.
- **Message pipeline:** all incoming chat messages pass through `lib/utils/text.ts` —
  `cleanMessageText` strips Python-style stringified lists and resolves escapes;
  command `<command-message>` tags are reduced to a single clean header; internal
  checkpoints and notifications are filtered out.

### Key directories

- `/app` — Next.js App Router (pages, API routes, layout)
- `/components` — shared React components
- `/hooks` — custom React hooks (theming, session state)
- `/lib` — core logic (API clients, design tokens, utilities)
- `/styles` — global CSS and third-party theme overrides

## Invariants

- **No terminal concepts in the frontend.** The following must never exist here: tmux
  concepts (panes, splits, pane IDs, layout grids, `execSync("tmux ...")`); Ink (React
  terminal renderer) components or imports; state machines ported from the Python TUI
  (`reduce_state`, `TreeInteractionState`); "sticky sessions" as a layout concept
  (a tmux pane-grid pattern); SSH/remote tmux attachment logic; any file with comments
  like "Ported from", "Source: \*.py", or "Faithful port"; any import from a `cli/`
  subdirectory into `app/` or `components/`.
- **What belongs here:** Next.js App Router pages and API routes; React Server and
  Client Components following Next.js conventions; standard web UI patterns (modals,
  sidebars, responsive layouts, navigation); web-native state management (React state,
  server state, URL state).
- **Design-system source of truth is `lib/theme/tokens.css`** — all hex codes as CSS
  variables (edit this file for IDE color support). `app/globals.css` imports the tokens
  and maps them to Tailwind 4 semantic classes (`bg-background`, `text-primary`).
  `lib/theme/tokens.ts` is a synced copy for non-CSS contexts (Canvas, terminal
  rendering). Dark mode is handled via `next-themes` and an explicit `.dark` class.
- **WebSocket features require the custom dev server.** `pnpm dev` (alias `pnpm dev:ws`)
  runs the WebSocket-capable server; raw `next dev` (`pnpm dev:next`) leaves `/api/ws`
  non-functional.

## Primary flows

### Development

Prerequisites: Node.js (v22+ recommended), pnpm, a running TeleClaude daemon.

```bash
pnpm dev       # custom dev server with WebSocket support
pnpm dev:next  # raw Next.js only; no live WebSocket features
pnpm dev:ws    # alias for the WebSocket-capable dev server
pnpm db:push   # push schema changes to SQLite (teleclaude-web.db)
pnpm db:studio # open Drizzle Studio
pnpm start     # custom production server
```

### Code quality

- Linting: `pnpm lint` (ESLint with Next.js config).
- Type checking: `npx tsc --noEmit` (strict TypeScript).
- Secrets/local overrides live in `.env` (template: `.env.example`).

## Failure modes

- **Live session-tree appears broken in dev** — started raw `next dev` instead of the
  custom server, so `/api/ws` is dead. Use `pnpm dev`.
- **Treating `pnpm build` as a smoke test** — a successful build is not proof the
  changed UI works. See `frontend-verification` for the real post-work check.
- **Referencing the Python TUI as a source** — if a feature has you reaching for the
  Python TUI, stop and design the web UX from web-native patterns.
