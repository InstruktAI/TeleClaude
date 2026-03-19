# Requirements: TypeScript Migration

## Goal

Migrate the TeleClaude Python daemon and CLI to TypeScript running on Bun, eliminating the
uvicorn/FastAPI HTTP server (source of asyncio degradation), moving to a single unified
TypeScript codebase for all daemon, API, and CLI concerns. The Textual TUI stays Python but
is decoupled to a pure API client. The Next.js frontend moves to the project root.

Prior research: `todos/api-migration-research.md`.

---

## Architecture

### Runtime and tooling

- **Bun** — runtime and package manager (replaces Node.js/pnpm for daemon and CLI)
- **Bun native SQLite** — replaces `better-sqlite3` (Drizzle `bun:sqlite` adapter)
- **TypeScript** — strict, no `any`, Zod for runtime validation at boundaries
- **Hono** — HTTP/WebSocket server in the Bun daemon (lightweight, Bun-native)
- **Vitest** — test runner (already in use)
- **Biome** — linter + formatter (replaces ESLint + Prettier for daemon/CLI code)

### Process topology (unchanged from Python era)

```
[Bun daemon]          ← replaces Python daemon, same Unix socket, same HTTP API
    ↑ Unix socket (/tmp/teleclaude-api.sock)
[Next.js frontend]    ← moves to project root, proxy layer unchanged
[Textual TUI]         ← stays Python, talks to daemon via HTTP API only
[telec CLI (TS)]      ← replaces Python telec, talks to daemon via Unix socket
```

The daemon runs as a persistent launchd service. Next.js proxy (`lib/proxy/daemon-client.ts`,
`ws-bridge.ts`) and identity header forwarding are unchanged.

### Repo structure after migration

```
TeleClaude/                   ← project root (frontend/ content moves here)
├── app/                      ← Next.js App Router (unchanged)
├── components/               ← React components (unchanged)
├── lib/                      ← Frontend lib (proxy/ stays, no changes)
├── server/                   ← NEW: TypeScript daemon (ported from Python)
│   ├── core/                 ← teleclaude/core/
│   ├── adapters/             ← teleclaude/adapters/
│   ├── events/               ← teleclaude/events/
│   ├── hooks/                ← teleclaude/hooks/
│   ├── transport/            ← teleclaude/transport/
│   ├── services/             ← teleclaude/services/
│   ├── config/               ← teleclaude/config/
│   ├── channels/             ← teleclaude/channels/
│   ├── memory/               ← teleclaude/memory/
│   ├── mirrors/              ← teleclaude/mirrors/
│   ├── db/                   ← teleclaude/core/db/ (Drizzle + Bun SQLite)
│   └── types/                ← teleclaude/api_models.py → Zod schemas + TS types
├── cli/                      ← TypeScript telec CLI (replaces Python telec)
├── server.ts                 ← Bun daemon entry point (Hono HTTP + WS + daemon init)
├── package.json              ← updated (bun, hono, etc.)
├── teleclaude/               ← Python package, shrunk to ~25k lines
│   ├── cli/tui/              ← Textual TUI (stays, decoupled)
│   ├── cli/api_client.py     ← HTTP client for daemon API (stays)
│   ├── cli/models.py         ← Python DTOs (stays)
│   └── install/              ← git wrapper, hook installers (stays)
├── pyproject.toml
└── Makefile
```

---

## Scope

### In scope

#### 1. Repo restructuring

- Move `frontend/` content to project root
- Keep `teleclaude/` Python package alongside
- Update all path references, Makefile, launchd plist, CI

#### 2. Runtime switch

- Replace `pnpm` with `bun` as package manager
- Replace `better-sqlite3` + Node.js SQLite usage with Bun native SQLite
- Update Drizzle config to use `bun:sqlite` adapter
- Update `package.json` scripts: `bun run --bun next dev`, `bun run --bun next build`
- Add `runtime: "nodejs"` to `middleware.ts` (Vercel Bun requirement)
- Remove `tsx` from devDependencies (Bun runs TS natively)
- Test `sharp` under Bun; fallback to `unoptimized: true` in Next.js config if needed

#### 3. TypeScript daemon (`server/`)

Port all Python daemon modules to TypeScript. Preserve the existing HTTP/WebSocket API
contract exactly — no endpoint changes, no payload changes, no auth changes during migration.

**Modules to port (by domain):**

| Python source                             | TypeScript target            | Lines |
| ----------------------------------------- | ---------------------------- | ----- |
| `teleclaude/core/` (excl. db, models)     | `server/core/`               | ~30k  |
| `teleclaude/adapters/`                    | `server/adapters/`           | ~10k  |
| `teleclaude/events/`                      | `server/events/`             | ~6k   |
| `teleclaude/hooks/`                       | `server/hooks/`              | ~4k   |
| `teleclaude/transport/`                   | `server/transport/`          | ~2k   |
| `teleclaude/services/`                    | `server/services/`           | ~1k   |
| `teleclaude/config/`                      | `server/config/`             | ~2k   |
| `teleclaude/channels/`                    | `server/channels/`           | ~0.5k |
| `teleclaude/memory/`                      | `server/memory/`             | ~1k   |
| `teleclaude/mirrors/`                     | `server/mirrors/`            | ~1k   |
| `teleclaude/core/db/`                     | `server/db/`                 | ~3k   |
| `teleclaude/api_models.py`                | `server/types/`              | ~0.6k |
| `teleclaude/daemon*.py` + `api_server.py` | `server.ts`                  | ~4k   |
| `teleclaude/context_selector.py`          | `server/context-selector.ts` | ~1k   |
| `teleclaude/docs_index.py`                | `server/docs-index.ts`       | ~0.6k |

**Key subsystems requiring special care:**

- `core/next_machine/` — AI agent state machines, complex domain logic
- `daemon_hook_outbox.py` — hook delivery with backpressure/retry logic
- `hooks/receiver/` — hook normalisation, complex parsing
- `adapters/telegram/` + `adapters/discord/` — platform SDK integration

#### 4. TypeScript CLI (`cli/`)

Replace `teleclaude/cli/telec/` (Python, ~5k lines) with TypeScript. Same command surface.

- All `telec <subcommand>` commands become TypeScript
- `telec tui` — new subcommand, spawns `python -m teleclaude.cli.tui` as subprocess
- `telec tui` replaces the current default `telec` (bare) which opens the TUI directly
- Plain Bun CLI — argument parsing with a lightweight library (e.g. `citty` or `yargs`)
- Talks to daemon via Unix socket (same as Python version)

#### 5. TUI decoupling (prerequisite to deleting Python daemon code)

The TUI currently imports daemon internals directly. These must be replaced with API calls
before the Python daemon code is deleted.

**API gaps to fill in the TypeScript daemon** (endpoints that don't exist yet):

| Currently imported in TUI                                 | New API endpoint                           |
| --------------------------------------------------------- | ------------------------------------------ |
| `teleclaude.config` (full config read)                    | `GET /api/config`                          |
| `teleclaude.cli.config_handlers.set_env_var`              | `POST /api/config/env`                     |
| `teleclaude.cli.config_handlers.get_person_config`        | Already: `GET /api/people` — extend        |
| `teleclaude.core.agents.get_enabled_agents`               | `GET /api/agents` (extend existing)        |
| `PreparePhase`, `IntegrationPhase`, `DOR_READY_THRESHOLD` | Computed fields in todo state API response |
| `teleclaude.constants.WORKTREE_DIR`                       | Part of `GET /api/config` response         |
| `teleclaude.constants.SlashCommand`                       | `GET /api/meta/commands`                   |
| `teleclaude.paths.TUI_STATE_PATH`                         | Remove — define locally in TUI package     |

**TUI refactor:** Replace all direct daemon imports with `api_client.py` calls. No other
TUI changes. TUI behaviour must be identical after decoupling.

#### 6. Daemon deletion

Once TypeScript daemon is live and TUI is decoupled:

- Delete `teleclaude/core/`, `teleclaude/adapters/`, `teleclaude/events/`, `teleclaude/hooks/`,
  `teleclaude/transport/`, `teleclaude/services/`, `teleclaude/api/`, `teleclaude/api_server.py`,
  `teleclaude/daemon*.py`, `teleclaude/config/`, `teleclaude/channels/`, `teleclaude/memory/`,
  `teleclaude/mirrors/`, etc.
- Remove `fastapi`, `uvicorn`, `pydantic`, `aiohttp`, `aiosqlite` from `pyproject.toml`
- Update launchd plist to run `bun server.ts` instead of Python daemon
- Update `Makefile` targets

### Out of scope

- Changes to the TUI's visual design or feature set
- New daemon features or API endpoints (beyond the 8 gap-fill endpoints above)
- Web frontend feature changes
- The `web-tui-parity` todo — it depends on this migration; reassess after
- `pylint-cleanup` todos — they touch code that will be deleted; pause them
- `session-runtime-overhaul` — reassess after TypeScript daemon is running

---

## Migration approach

Phased, coexistence. Python daemon and TypeScript daemon run in parallel during transition.
API contract frozen — no changes until TypeScript daemon is fully live. Each phase is
independently deployable and testable.

### Phase 1 — Foundation (unblocked, runs first)

- Repo restructure: `frontend/` → project root
- Runtime switch: pnpm → bun, `better-sqlite3` → Bun SQLite
- TypeScript project setup: `tsconfig.json`, Biome, Vitest config for `server/`
- Port `server/types/` (Zod schemas from `api_models.py`)
- Port `server/config/` (config loading, YAML parsing)
- Port `server/db/` (Drizzle schema, migrations, query layer)
- Port `server/transport/` (Redis client)

### Phase 2 — Core domain (after Phase 1)

- Port `server/core/models/`
- Port `server/core/db/` query handlers
- Port `server/core/command_handlers/`
- Port `server/core/agent_coordinator/`
- Port `server/services/` (monitoring, maintenance)
- Port `server/channels/`, `server/memory/`, `server/mirrors/`

### Phase 3 — API surface (after Phase 2)

- Implement Hono HTTP server in `server.ts`
- Port all 26 endpoints from `teleclaude/api/` + `api_server.py`
- Port WebSocket server
- Add 8 new gap-fill endpoints (config, agents, meta)
- Shadow-run alongside Python daemon, validate parity

### Phase 4 — Events, hooks, adapters (parallel with Phase 3)

- Port `server/events/` pipeline + cartridges
- Port `server/hooks/` receiver + normalizers
- Port `server/adapters/` (Telegram, Discord, QoS, UI)

### Phase 5 — State machines (parallel with Phase 4)

- Port `server/core/next_machine/` (prepare, work, integrate state machines)
- Port `server/core/integration/`
- Port `server/core/operations/`
- Port `server/core/tmux_bridge/`

### Phase 6 — TypeScript CLI (parallel with Phases 3–5)

- Port `cli/` TypeScript telec CLI
- All subcommands except `telec tui`
- `telec tui` subprocess launcher

### Phase 7 — TUI decoupling (after Phase 3 gap-fill endpoints are live)

- Refactor `teleclaude/cli/tui/` to replace all daemon imports with `api_client.py` calls
- Validate: TUI behaviour identical

### Phase 8 — Cutover and cleanup

- Switch launchd plist to TypeScript daemon
- Decommission Python daemon
- Delete daemon Python modules
- Remove Python daemon dependencies from `pyproject.toml`
- Update CI, Makefile, documentation
- Reassess `web-tui-parity` and `session-runtime-overhaul` in new context

---

## Success criteria

- [ ] Python daemon process no longer runs; Bun daemon handles all requests
- [ ] All 26 existing API endpoints respond identically to Python daemon
- [ ] WebSocket push events work identically
- [ ] Telegram, Discord adapters functional
- [ ] TUI has zero imports from deleted Python modules; behaviour unchanged
- [ ] `telec` CLI TypeScript — all subcommands functional including `telec tui`
- [ ] `asyncio_tasks` warning gone (uvicorn eliminated)
- [ ] `bun test` green across `server/` and `cli/`
- [ ] `bun run build` + `bun run --bun next build` succeed
- [ ] launchd plist updated; daemon restarts correctly on macOS
- [ ] `teleclaude` Python package size ≤ 25k lines

---

## Constraints

- API contract frozen during migration — no breaking changes until cutover
- `teleclaude/cli/tui/` must not be modified until Phase 7 (after gap-fill endpoints live)
- The proxy layer (`lib/proxy/`) stays — daemon remains a separate process
- Bun is the runtime; no Node.js fallback for the daemon
- Migration branch: `ts-migration` — no direct commits on `main` for this work
- The `pylint-cleanup` todos (1–8) should be paused; they add churn to code being deleted

---

## Risks

| Risk                                                  | Severity | Mitigation                                                   |
| ----------------------------------------------------- | -------- | ------------------------------------------------------------ |
| `sharp` native addon fails under Bun                  | Low      | Disable Next.js image optimization as fallback               |
| Bun edge cases in Next.js 15                          | Low      | Vercel beta support confirmed; test early                    |
| State machine complexity in `core/next_machine/`      | High     | Port last, with dedicated review lane                        |
| Hook outbox backpressure logic                        | Medium   | Port with full test coverage, shadow-run against Python      |
| TypeScript daemon introduces new bugs at cutover      | Medium   | Shadow-run both daemons in parallel (Phase 3) before cutover |
| TUI breaks when daemon Python code deleted            | Medium   | TUI decoupling (Phase 7) is a hard prerequisite for Phase 8  |
| Pylint cleanup todos merge against-to-be-deleted code | Low      | Pause them now                                               |
