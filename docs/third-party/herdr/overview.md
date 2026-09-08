---
description: HerdR terminal-workspace-manager architecture, CLI/socket API, and Claude Code hook-integration behavior (version 0.9.0).
---

# What it is

HerdR ("the runtime your coding agents live on") is a Rust terminal
multiplexer purpose-built for hosting AI coding-agent CLIs. It runs as a
**headless server** that owns PTYs directly: the server process is the OS
parent of each pane's shell, and a native agent CLI started in a pane is a
child of that shell (a single hop below the server). A separate **client**
(its own TUI, or the bare CLI) renders or inspects panes over a local
socket; panes and their child processes persist independently of whether any
client is attached.

- Upstream: <https://herdr.dev>, source at
  <https://github.com/ogulcancelik/herdr>. `Cargo.toml` declares
  `repository = "https://github.com/herdrdev/herdr"`; that URL does not
  resolve to a distinct project — `ogulcancelik/herdr` is the repository the
  Homebrew formula builds from and matches the installed version.
- Version: 0.9.0, the version Homebrew's bottled formula installs.
- License: **Apache-2.0** — stated in the repository's `LICENSE` file,
  `Cargo.toml`'s `license` field, and the Homebrew formula's metadata. The
  separately published crates.io `herdr` crate (v0.1.0, license field
  `AGPL-3.0-or-later`) is an unrelated, stale publish and is not the
  distribution channel the project documents.

# Canonical fields

## Distribution and footprint

- Homebrew core formula (bottled, no build required): `brew install herdr`.
  A single Cellar entry, ~22MB/15 files, with **no forced background
  service** — the formula's own caveat offers `herdr server` as the
  alternative to `brew services start herdr` for anyone who does not want a
  persistent service. Reversible via `brew uninstall herdr`.
- Building from source requires a **Zig 0.15.2** toolchain in addition to
  Rust, to compile a vendored `libghostty-vt` (Ghostty's terminal-parsing
  engine, under `vendor/`) via `build.rs`; `cargo build --release` fails
  without `zig` on `PATH` (or the `ZIG` env var). The bottled Homebrew
  install does not require this.
- Other install paths per upstream docs: `curl -fsSL https://herdr.dev/install.sh | sh`,
  `mise use -g herdr`, a Windows PowerShell installer.
- Config: `~/.config/herdr/config.toml`. Logs: `~/.config/herdr/herdr*.log`.
  Default API/client sockets: `~/.config/herdr/herdr.sock` and
  `~/.config/herdr/herdr-client.sock` (named sessions get their own
  `~/.config/herdr/sessions/<name>/herdr.sock`).

## CLI surface (agent + pane control)

- `herdr agent start <NAME> --kind <KIND> --pane <ID> [--timeout <MS>] [-- AGENT_ARG...]`
  starts one of 21 recognized agent kinds (`claude` included) in an
  **existing pane that must already be at an interactive shell prompt**.
  Success means the kind was detected and is interactive-ready.
- Panes/tabs/workspaces are created over the socket API without any TUI
  client: `herdr workspace create [--cwd PATH] [--label TEXT] [--env K=V]
[--focus|--no-focus]`, `herdr tab create --workspace <ID> ...`. A freshly
  created workspace's `root_pane` is a plain interactive shell — there is no
  flag to launch an arbitrary command directly as a pane's first process.
- `herdr pane run <PANE_ID> <COMMAND>...` runs a command in an existing
  pane by **synthesizing a single line and typing it into the pane's shell**
  rather than exec'ing an argv array: an argument containing shell
  metacharacters (`;`, spaces meant to stay one token) is not preserved as
  one token, since the pane's own shell re-parses the synthesized line and
  splits on them. The call also returns as soon as the line is typed; it
  does not block for the launched command's duration.
- `herdr pane close <PANE_ID>` closes a pane and its whole process subtree.
- `herdr pane read <PANE_ID> --source <SOURCE> --format <text|ansi>` reads
  pane content. `--source recent` is base/scrollback content and does not
  include what a full-screen TUI has drawn to the alternate screen;
  `--source visible` is the live rendered viewport and is what shows a
  running TUI's current screen; `--source detection` is the narrower
  bottom-buffer snapshot the project's own status detector reads.
- `herdr pane report-agent` / `herdr pane report-agent-session` /
  `herdr pane release-agent`: a **self-report** path distinct from screen
  detection — an agent or its integration can push
  `{pane_id, source, agent, state, agent_session_id, seq}` directly. This is
  how the bundled OpenCode integration reports state; it is not exercised by
  simply running a raw agent binary in a pane.

## Socket/IPC API

- Newline-delimited JSON over a Unix domain socket (named pipe on Windows).
  Every CLI subcommand above is a thin client over this same socket — the
  full lifecycle (create workspace, start agent, read pane, close pane) is
  reachable against a bare `herdr server` with no TUI client involved.
- `herdr api schema --json` dumps the full bundled JSON Schema (~275KB at
  0.9.0, schema_version 1, protocol 22) for every request/event/response
  shape, as bare types (`properties`/`required`/`$ref`), not prose-documented.
- Event vocabulary is a **closed, fixed set** of pane/workspace/tab/agent
  CRUD-style events (`pane.created`, `pane.agent_status_changed`,
  `workspace.renamed`, etc.). There is no `permission` concept anywhere in
  the schema — no permission-request/response event or method exists.
  `pane.agent_status_changed`'s `agent_status` is one of `idle`, `working`,
  `blocked`, `done`, `unknown`.
- `pane.report_agent[_session]` carries `agent_session_id` (nullable
  string) and `seq` (monotonic uint64) alongside the pane's own persistent
  `pane_id`/`terminal_id`, as the primitive for distinguishing one agent run
  from a later, different run that reuses the same pane. The bundled
  OpenCode plugin (`src/integration/assets/opencode/herdr-agent-state.js`)
  uses it by explicitly tracking child-session ids in a map "so their
  events cannot replace the pane's root session," reducing OpenCode's own
  richer event stream (`permission.asked`, `tool.execute.before`,
  `session.status`, …) down to the five-value status enum before calling
  `pane.report_agent`. The call is fire-and-forget: a 500ms socket timeout,
  discarding the result on any reply, error, or timeout alike. HerdR never
  returns a decision through this channel; it only records state.
- The same file shows the plugin-side integration contract: HerdR injects
  `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and `HERDR_PANE_ID` into a pane's
  environment; a plugin loaded by the hosted agent reads those to connect
  back to HerdR's socket and self-report, correlated by pane id.

## Claude Code hook integration (`src/integration/claude_settings.rs`)

- Install/uninstall edits are additive by design (source comment:
  "preserves unrelated hooks in each agent's native format instead of
  normalizing user configuration"). `install()` adds or repairs exactly one
  hook entry, under `hooks.SessionStart`, matcher `"*"`, pointing at HerdR's
  own hook binary with argument `session`. Matching, for both install
  (idempotency) and uninstall (removal), is by **exact command-string
  equality** against HerdR's own previously-installed command — never a
  blanket clear of the array or of the `SessionStart` key, so another tool's
  entries under the same event are left untouched by construction.
- `HOOK_REMOVALS` additionally names other Claude event keys (`PreToolUse`,
  `PostToolUse`, `Stop`, `SessionEnd`, etc.) that `install()`/`uninstall()`
  clean up if a HerdR-owned entry from an older version is found there; the
  0.9.0 installer does not add new entries for those events. Live status for
  Claude is obtained by screen detection (`AGENTS.md`: "Screen detection is
  evidence-based... reads a screen snapshot"), not a dense hook set.

# Sources

- <https://herdr.dev>
- <https://github.com/ogulcancelik/herdr>
- <https://formulae.brew.sh/formula/herdr>
