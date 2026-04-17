# Changelog

All notable changes to TeleClaude are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] - 2026-04-10

### Added

- **todos.db:** SQLite-backed todo state store replaces filesystem `todos/` — state, artifacts, roadmap, and delivered entries all live in a per-project database
- **todos.db:** CLI handlers for `todo show`, `todo artifacts read/write/list`, `todo stamp`, with API routes to match
- **todos.db:** UUID primary keys and delivered slug reuse, filesystem-to-DB migration script
- **web-tui:** Two-panel TUI layout with session tree and keyboard navigation
- **web-tui:** Preparation, configuration, and jobs views
- **identity:** Unified identity resolution across all session origins (terminal, web, adapters, daemon)
- **output-delivery:** Adapter-owned output pull architecture replacing scattered output routing
- **memory-extraction:** Session memory extraction pipeline
- **chiptunes:** SID music player with HVSC song duration lookup and fade-out
- **chiptunes:** Stop button, dislike button for filtering unwanted songs
- **lint:** Scoped lint, test, and type-check to session-touched files in agent sessions
- **cli:** `--draft` and `--prepped` flags for `telec todo dump`
- **cli:** Register `todo read/write/stamp/artifacts` in CLI surface
- **adapters:** GFM markdown split engine and flavor-routed overflow for long messages
- **listeners:** One-shot listener support with auto-registration on plain send
- **reflection:** User input reflection, output formatting, and agent rendering
- **agent-cli:** Preserve TeleClaude context through Codex compaction
- **cadence:** Replace cursor-driven rendering with file-derived authority
- **activation-trigger:** Validate and surface activatable procedures in distribution
- **integration:** Surface anomalies from silent failure points to agents
- **reconcile:** Idempotent filesystem-to-DB reconciliation
- **tui:** Icebox toggle and display in preparation pane
- **tui:** Render `I:ready` label for `finalize_ready` state
- **db:** Unified SQLite access behind shared SQLAlchemy connection factory
- **jobs:** Project backup cron job for todo DB snapshot and S3 upload
- **services:** v2 service-oriented architecture scaffolding
- **events:** Route `todo_dumped` by kind via lifecycle router cartridge
- **todo-watcher:** OS-managed todo file watchers
- **docs:** Untrack `index.yaml` files — treat as generated artifacts
- **history:** Role-aware session history

### Changed

- **storage:** Migrate state machine from `todos/` filesystem to `todos.db`
- **storage:** Remove `roadmap.yaml`, `icebox.yaml`, and `delivered.yaml` — all in DB now
- **state-machine:** Per-step prerequisites and DB-native `mark_phase`
- **edge-http:** Move internal callers to HTTP edge layer
- **adapters:** Collapse `ThreadedOutputMixin` and `OutputDeliveryMixin` into `UiAdapter`
- **adapters:** Invert markdown strategy from mixin to adapter
- **identity:** Remove legacy origin metadata and simplify identity pipeline
- **session:** Dissolve `SessionMetadata`, unify origins
- **config:** Make `GlobalConfig`, `ProjectConfig`, and `PersonConfig` independent schemas
- **db:** Move main database to `~/.teleclaude/teleclaude.db`, mirrors to separate database
- **db:** Fresh initial schema with NullPool (SQLite gains nothing from connection pooling)
- **logging:** Migrate stdlib logging to `instrukt_ai_logging` across codebase
- **paths:** Eliminate all hardcoded `~/.teleclaude` paths — centralize in paths module
- **chiptunes:** Decouple player from daemon — worker owns state
- **cli:** Remove DTO alias layer, unify on `TodoDTO`
- **integration:** Replace stateful readiness projection with stateless `deployment.started` trigger
- Remove dynamic event cartridge system
- Remove launchd cron installer

### Fixed

- **hooks:** Restage formatter edits on `rc!=0` and retry pre-commit
- **hooks:** Auto-restage formatter-modified files in pre-commit wrapper
- **prepare:** Update `base_sha` in `RE_GROUNDING` to prevent infinite loop
- **prepare:** Restamp artifact digests on re-entry to prevent staleness loop
- **prepare:** Centralize worktree cwd resolution in dispatcher
- **asyncio:** Eliminate task leaks from `wait_for(event.wait())` pattern
- **output:** Restore pipeline session visibility on Discord admin lane
- **output:** Consolidate turn-break and close TOCTOU delivery race
- **integration:** Stop system prompt reflection crash
- **integration:** Propagate caller identity through integrator spawn chain
- **operations:** Preserve caller identity through daemon handoffs
- **db:** Plug SQLAlchemy engine leak, switch to NullPool
- **todos_db:** Add slug validation, remove contract-breaking fallbacks
- **todos_db:** Fix artifact_versions migration skipping tables with integer PK
- **cache:** Emit mutation signal from `TodosDb` to invalidate TUI todos cache
- **git-wrapper:** Rewrite in bash — Python startup caused process storm
- **git-wrapper:** Block blind merge resolution and sweep-add on main
- **discord:** Break threaded turn before broadcasting user input
- **telegram:** Treat `Topic_not_modified` as no-op, evict stale topic cache
- **chiptunes:** Reset position on track advance, skip CIA-timer tracks, fix prebuffer
- **chiptunes:** Fade AFTER listed duration, use SID's default subtune for duration
- **cli:** Ignore stale temp identity in `tc_tui` sessions
- **api:** Add global exception handler, fix `todo_dump` 500
- **regression:** Restore project config, doc snippets, and guardrails after blind merge
- **worktrees:** Remove symlink approach — workers need real tracked dirs
- **mirrors:** Fully separate mirrors from main database
- **coordinator:** Advance cadence cursor on UI input to prevent re-delivery
- **markdown:** Split at word boundaries in GFM and WhatsApp truncation

**Full diff:** [v0.4.0...v0.5.0](https://github.com/InstruktAI/TeleClaude/compare/v0.4.0...v0.5.0)

## [0.4.0] - 2026-03-21

### Added

- **cli:** `telec memories list` subcommand

### Changed

- **models:** Consolidate `ThinkingMode` — single import from `helpers/agent_types`

### Fixed

- **auth:** Remove token TTL and simplify `session_tokens` schema
- **identity:** Return empty context for API-origin sessions
- **checkpoint:** Watch all `templates/` for setup changes
- **work-machine:** Accept work-phase states in preparation precondition check

**Full diff:** [v0.3.0...v0.4.0](https://github.com/InstruktAI/TeleClaude/compare/v0.3.0...v0.4.0)

## [0.3.0] - 2026-03-20

Initial tagged release of TeleClaude.

### Added

- **Multi-agent orchestration** — Claude, Codex, and Gemini as parallel work lanes with AI consensus arbitration
- **Telegram adapter** — Full session management with topic-based threading and rich output
- **Discord adapter** — Team channels, admin lanes, and threaded output delivery
- **Session lifecycle** — Daemon-managed tmux sessions with start, send, end, restart, and revive
- **Todo/roadmap workflow** — Creative, prepare, work, and integrate lifecycle phases with state machines
- **Release automation** — AI-powered release inspection with multi-lane consensus and semver classification
- **CLI surface** — `telec` command with sessions, agents, docs, todo, roadmap, config, and auth subcommands
- **Git safety wrapper** — PATH-based binary wrapper blocking stash, checkout, restore, and reset in agent sessions
- **Agent artifact distribution** — Master file inflation, multi-agent transpilation, and runtime deployment
- **Documentation system** — Two-phase `telec docs index` / `telec docs get` with taxonomy-based snippet retrieval
- **Output polling** — Unified output delivery from agent sessions to UI adapters
- **Identity and auth** — Terminal login, session tokens for system principals, role-based authorization
- **Configuration** — Global, project, and per-person config with YAML schemas and validation
- **Event system** — Domain-scoped event schemas with cartridge-based routing
- **Integration engine** — Worktree-based integration with lease acquisition and merge verification
- **Cron runner** — Scheduled jobs with script and agent execution modes
- **Web interface** — NextAuth-based login with OTP email verification
