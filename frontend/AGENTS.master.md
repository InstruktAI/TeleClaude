@../AGENTS.md

# TeleClaude Frontend — Project Overview & Instructions

This directory is a **Next.js web application**. It is NOT a terminal UI and must NOT contain terminal, TUI, or Python TUI concepts.

## Architecture Boundary — MANDATORY

The TeleClaude project has two separate UIs with completely different architectures:

|                 | Python TUI                             | This Frontend                          |
| --------------- | -------------------------------------- | -------------------------------------- |
| **Location**    | `teleclaude/cli/tui/`                  | `frontend/`                            |
| **Framework**   | Python Textual + tmux                  | Next.js + React                        |
| **Runs in**     | Terminal                               | Browser                                |
| **State**       | Dataclass + reducer                    | React state / server state             |
| **Layout**      | Tmux pane splits                       | CSS / responsive web layout            |
| **Interaction** | Keyboard-driven, double-press gestures | Standard web UX (click, hover, modals) |

**These are independent applications. There is no shared architecture between them.**

### What MUST NOT exist in this frontend

- Tmux concepts: panes, splits, pane IDs, layout grids, `execSync("tmux ...")`
- Ink (React terminal renderer) components or imports
- State machines ported from the Python TUI (`reduce_state`, `TreeInteractionState`)
- Double-press gesture detection or terminal interaction patterns
- "Sticky sessions" as a layout concept (this is a tmux pane grid pattern)
- SSH/remote tmux attachment logic
- Any file with comments like "Ported from", "Source: \*.py", or "Faithful port"
- Any import from a `cli/` subdirectory into `app/` or `components/`

### What belongs here

- Next.js App Router pages and API routes
- React Server Components and Client Components following Next.js conventions
- Standard web UI patterns: modals, sidebars, responsive layouts, navigation
- API calls to the TeleClaude daemon via HTTP/WebSocket proxy
- Web-native state management (React state, server state, URL state)

**If you are building a feature and find yourself referencing the Python TUI as a source, STOP. Design the web UX from scratch using web-native patterns. The Python TUI solves terminal constraints that do not exist in a browser.**

---

## Building and Running

### Prerequisites

- Node.js (v22+ recommended)
- pnpm (package manager)
- Running TeleClaude Daemon (accessible via `/tmp/teleclaude-api.sock`)

### Development

```bash
pnpm dev       # Start Next.js with Turbopack
pnpm dev:ws    # Start custom server with WebSocket support
```

### Production

```bash
pnpm build     # Build standalone Next.js bundle
pnpm start     # Start the custom production server
```

### Database & Auth

```bash
pnpm db:push   # Push schema changes to SQLite (teleclaude-web.db)
pnpm db:studio # Open Drizzle Studio to inspect data
```

---

## Design System & Theming

The frontend uses a **Master Source** architecture to keep colors consistent across all interfaces.

- **Source of Truth:** `lib/theme/tokens.css` contains all hex codes as CSS variables. **Edit this file** to get full IDE support (color pickers, auto-completion).
- **Tailwind 4 Integration:** `app/globals.css` imports the tokens and maps them to Tailwind's semantic classes (e.g., `bg-background`, `text-primary`).
- **Logic Layer:** `lib/theme/tokens.ts` maintains a synced copy of tokens for non-CSS contexts like Canvas animations and terminal rendering.
- **Dark Mode:** Handled via `next-themes` and an explicit `.dark` class. The system automatically detects OS preference but allows manual overrides via the `DarkModeToggle` component.

---

## Development Conventions

### Message Pipeline

All incoming chat messages pass through a robust cleaning utility:

- **Location:** `lib/utils/text.ts`
- **Functions:**
  - `cleanMessageText`: Strips Python-style stringified lists and resolves escapes.
  - **Command Reformatting:** Intercepts `<command-message>` tags and reduces them to a single clean header (e.g., `/next-work ...`), discarding technical body content.
  - **System Filtering:** Automatically hides internal checkpoints and notifications.

### API Proxy

The frontend does not communicate directly with external services. Instead, it proxies all requests to the TeleClaude daemon via:

- **SSE Streaming:** `app/api/chat/route.ts` transforms the daemon stream into an AI SDK-compatible format.
- **WebSocket Bridge:** `server.ts` handles auth-guarded WebSocket upgrades for real-time updates.

### Code Quality

- **Linting:** `pnpm lint` (uses ESLint with Next.js config).
- **Type Checking:** `npx tsc --noEmit` (ensures strict TypeScript compliance).
- **Environment:** Secrets and local overrides should be managed in `.env` (use `.env.example` as a template).

---

## Key Directory Structure

- `/app`: Next.js App Router (pages, API routes, layout).
- `/components`: Shared React components (Assistant, Parts, Sidebar).
- `/hooks`: Custom React hooks (Theming, Session state).
- `/lib`: Core logic (API clients, design tokens, utility functions).
- `/styles`: Global CSS and third-party theme overrides.
