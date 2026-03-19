# Input: TypeScript Migration

## Origin

Initiated 2026-03-19 after sustained asyncio task accumulation warnings (`asyncio_tasks=6790`,
threshold 500). Root cause traced to uvicorn/FastAPI HTTP server degradation — a problem 3
months old with no root cause found. See `todos/api-migration-research.md` for full prior
research.

The uvicorn degradation is a symptom of using Python for a long-running async daemon. The
decision: stop patching Python, migrate the daemon to TypeScript/Bun.

## Key decisions made (in order)

1. **Runtime: Bun** — Vercel officially supports Bun + Next.js in beta (all plans).
   The only required code change is replacing `better-sqlite3` with Bun's native SQLite
   via Drizzle's `bun:sqlite` adapter. All other packages are pure JS/TS and work identically.
   Bun replaces pnpm as the package manager too.

2. **Daemon stays a separate process** — NOT merged into Next.js. Long-running agent sessions
   must survive a web server restart. The proxy layer (lib/proxy/daemon-client.ts,
   ws-bridge.ts) stays. Identity headers stay. Same Unix socket path.

3. **Frontend moves to project root** — `frontend/` content becomes the repo root. The
   `teleclaude/` Python package stays alongside it.

4. **API ported to TypeScript** — same HTTP/WebSocket contract, same Unix socket path.
   No API contract changes during migration. Clients (Next.js proxy, TUI, telec CLI) are
   unaware during phased rollout.

5. **`telec` CLI rewritten in TypeScript** — plain Bun CLI, no Ink, no React. Same command
   surface. `telec tui` is a new subcommand that launches the Textual TUI as a subprocess.
   All other `telec` commands become TypeScript.

6. **TUI stays Python/Textual** — but must be decoupled from daemon internals before the
   daemon Python code is deleted. Currently imports directly from `teleclaude.core`,
   `teleclaude.config`, etc. After migration those modules don't exist in Python.

7. **`teleclaude` Python package shrinks** — from ~120k lines to ~25k. Keeps: TUI,
   api_client.py, cli models, install scripts, helpers (YouTube, mlx_utils). Loses: all
   daemon code.

## What NOT to do

- Do not merge daemon into Next.js process (session resilience requires separation)
- Do not use Ink for the CLI
- Do not break the API contract during migration (phased coexistence)
- Do not touch `teleclaude/cli/tui/` until TUI decoupling prerequisites are shipped
- Do not run pnpm after switching to Bun
- Do not start pylint cleanup todos until migration branch is cut (they generate churn on
  code that will be deleted)
