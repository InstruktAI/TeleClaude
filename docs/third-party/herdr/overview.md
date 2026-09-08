---
description: HerdR terminal-workspace-manager architecture, CLI/socket API, agent-hook integration behavior, and install footprint, verified from source (0.9.0) and live server testing.
---

# What it is

HerdR ("the runtime your coding agents live on") is a Rust terminal
multiplexer purpose-built for hosting AI coding-agent CLIs. It runs as a
**headless server** that owns PTYs directly: the server process is the OS
parent of each pane's shell, and a native agent CLI started in a pane is a
child of that shell (a single hop below the server, verified via live `ps`
ancestry). A separate **client** (its own TUI, or the bare CLI) renders or
inspects panes over a local socket; panes and their child processes persist
independently of whether any client is attached.

- Upstream: <https://herdr.dev>, source at
  <https://github.com/ogulcancelik/herdr> (repo `Cargo.toml` declares
  `repository = "https://github.com/herdrdev/herdr"`; the two did not resolve
  to a distinct second repository during this review — treat `ogulcancelik/herdr`
  as canonical, matching the Homebrew formula's build source and version).
- Version reviewed: 0.9.0 (current `master` at review time, and the version
  Homebrew's bottled formula installs).
- License: **Apache-2.0**, confirmed three ways — the repo's `LICENSE` file
  header, `Cargo.toml`'s `license` field, and the Homebrew formula's own
  metadata. crates.io's stand-alone `herdr` crate (v0.1.0, license field
  `AGPL-3.0-or-later`) is a stale, unrelated-vintage publish and is not the
  distribution channel the project documents or recommends — do not resolve
  license or version questions from that crate.

# Canonical fields

## Distribution and footprint

- Homebrew core formula (bottled, no build required): `brew install herdr`.
  Installs a single ~22MB/15-file Cellar entry with **no forced background
  service** — `brew services start herdr` is optional; the formula's own
  caveat says to just run `herdr server` (or plain `herdr`) if a persistent
  service isn't wanted. Fully reversible via `brew uninstall herdr`.
  Homebrew analytics at review time: ~50k installs/90 days (mature, broadly
  adopted, not a fringe tool).
- Building from source requires a **Zig 0.15.2** toolchain in addition to
  Rust, to compile a vendored `libghostty-vt` (Ghostty's terminal-parsing
  engine, vendored under `vendor/`) via `build.rs`. `cargo build --release`
  fails outright without `zig` on `PATH` (or `ZIG` env var). The bottled
  Homebrew install avoids this entirely.
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
- Panes/tabs/workspaces are created headlessly: `herdr workspace create
[--cwd PATH] [--label TEXT] [--env K=V] [--focus|--no-focus]`, `herdr tab
create --workspace <ID> ...`. A freshly created workspace's `root_pane` is
  a plain interactive shell — there is no flag to launch an arbitrary command
  directly as a pane's first process.
- `herdr pane run <PANE_ID> <COMMAND>...` runs a command in an existing pane.
  Verified behavior, not documented in `--help`:
  - It **synthesizes a single line and types it into the pane's shell**
    rather than exec'ing an argv array. An argument containing shell
    metacharacters (`;`, unescaped spaces meant to stay one token, etc.) is
    **not preserved as one token** — the pane's own shell (zsh/bash)
    re-parses the synthesized line and splits on them. A multi-word `-c`
    script string is the failure case actually hit during review.
  - The CLI call **returns as soon as the line is typed**; it does not block
    for the launched command's duration. The process keeps running in the
    pane after the CLI call returns.
- `herdr pane close <PANE_ID>` closes a pane and reliably tears down its
  whole process subtree (verified: shell and agent child both gone
  immediately after close, in every case tested including a live `claude`
  session).
- `herdr pane read <PANE_ID> --source <SOURCE> --format <text|ansi>` reads
  pane content. **`--source recent` is base/scrollback content and does not
  include what a full-screen TUI has drawn to the alternate screen.**
  `--source visible` is the live rendered viewport and is what actually shows
  a running TUI's current screen (confirmed by reading real Claude Code
  trust-dialog output through it). `--source detection` is the narrower
  bottom-buffer snapshot the project's own status detector reads.
- `herdr pane report-agent` / `herdr pane report-agent-session` /
  `herdr pane release-agent`: a **self-report** path distinct from screen
  detection — an agent or its integration can push
  `{pane_id, source, agent, state, agent_session_id, seq}` directly. This is
  how the bundled OpenCode integration works (see below); it is not exercised
  by simply running a raw agent binary in a pane.

## Socket/IPC API

- Newline-delimited JSON over a Unix domain socket (named pipe on Windows).
  Every CLI subcommand shown above is a thin client over this same socket —
  confirmed by running `herdr workspace create`, `herdr pane list`, `herdr
agent start`, etc. against a bare `herdr server` with **no TUI client ever
  started**; every call returned a structured JSON result headlessly.
- `herdr api schema --json` dumps the full bundled JSON Schema (~275KB at
  0.9.0, schema_version 1, protocol 22) for every request/event/response
  shape. It is bare types (`properties`/`required`/`$ref`), not prose-documented.
- Event vocabulary is a **closed, fixed set** of pane/workspace/tab/agent
  CRUD-style events (`pane.created`, `pane.agent_status_changed`,
  `workspace.renamed`, etc.). **There is no `permission` concept anywhere in
  the schema** — no permission-request/response event or method exists.
  `pane.agent_status_changed`'s `agent_status` is one of `idle`, `working`,
  `blocked`, `done`, `unknown`; that enum is the ceiling for anything routed
  through HerdR's own event bus.
- Correlation fields exist for pane reuse: `pane.report_agent[_session]`
  carry `agent_session_id` (nullable string) and `seq` (monotonic uint64)
  alongside the pane's own persistent `pane_id`/`terminal_id`. These are the
  primitive for telling "this event belongs to run X" from a later, different
  run of a different agent that happens to reuse the same pane — but using
  them correctly is the integration's job, not automatic. The bundled
  OpenCode plugin (`src/integration/assets/opencode/herdr-agent-state.js`)
  demonstrates the discipline required: it explicitly tracks child-session
  IDs in a map "so their events cannot replace the pane's root session,"
  reduces OpenCode's own rich event stream (`permission.asked`,
  `tool.execute.before`, `session.status`, …) down to HerdR's five-value
  status enum before calling `pane.report_agent`, and is fire-and-forget —
  it does not wait for or act on any response from HerdR (500ms socket
  timeout, discards on any reply/error/timeout alike). HerdR never sends a
  decision back through this channel; it only records state.
- The same file documents the plugin-side integration contract: HerdR
  injects `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and `HERDR_PANE_ID` into a
  pane's environment; a plugin loaded by the hosted agent reads those to
  connect back to HerdR's socket and self-report, correlated by pane id.

## Claude Code hook integration (`src/integration/claude_settings.rs`)

- Install/uninstall edits are **surgical and additive**, by design (source
  comment: "preserves unrelated hooks in each agent's native format instead
  of normalizing user configuration"). `install()` only ever adds/repairs
  **one** hook entry, under `hooks.SessionStart`, matcher `"*"`, pointing at
  HerdR's own hook binary with argument `session`. Matching for both install
  (idempotency) and uninstall (removal) is by **exact command-string
  equality** against HerdR's own previously-installed command — never a
  blanket clear of the array or of the `SessionStart` key.
- `HOOK_REMOVALS` additionally lists other Claude event names (`PreToolUse`,
  `PostToolUse`, `Stop`, `SessionEnd`, etc.) as things `install()`/`uninstall()`
  will clean up **if a HerdR-owned entry from an older version is found
  there**; the current 0.9.0 installer does not add new entries for any of
  those events. Live agent status for Claude is obtained by screen detection
  (`AGENTS.md`: "Screen detection is evidence-based... reads a screen
  snapshot"), not by a dense hook set.
- Verified against a real, populated `~/.claude/settings.json` already
  carrying a full set of TeleClaude's own hooks (`SessionStart`, `Stop`,
  `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, etc., each with matcher
  `"*"` and a distinct `teleclaude/hooks/receiver/__main__.py ...` command):
  HerdR's installer would append a **second, independent array entry** to
  `SessionStart` (own matcher `"*"`, own command) alongside TeleClaude's
  existing entry. Claude Code fires every matching array entry per event, so
  both commands run; nothing is overwritten or removed. This was confirmed
  by reading the installer's matching/removal logic against the actual
  deployed file, not by running the installer against it.

## Process-parenting topology (owning-terminal question)

Two arrangements were tested against a live `herdr server` + real `claude`:

1. **HerdR launches the native CLI directly** (`herdr agent start --kind
claude --pane <id>`): confirmed via `ps` ancestry that `herdr server` is
   the OS parent of the pane's shell, and that shell is the OS parent of
   `claude` (single hop, no launcher wrapper in between). An outside process
   is not the OS parent in this arrangement and cannot `wait()`/reap the
   agent directly; the only control/observation surface is HerdR's own
   socket API (`pane.read`, `pane.send_keys`, `agent.wait`, `pane.close`, …).
2. **A third-party wrapper is the pane's foreground command, and it spawns
   the native CLI on its own inner PTY**: works only if the wrapper's
   inherited stdin/stdout (which _is_ the pane's visible content) carries
   the raw inner-PTY bytes, and any separate protocol the wrapper needs goes
   over a channel it opens itself (e.g. a Unix socket), never over its own
   stdio. A first attempt that kept the wrapper's own stdout as a
   line-JSON protocol channel (reasonable in isolation) produced a pane that
   showed raw JSON instead of the agent's screen once dropped into a HerdR
   pane — concretely disproving that such a wrapper "just works" unmodified.
   A second, role-swapped version (raw passthrough on inherited stdio, JSON
   events on a self-opened socket) was built and confirmed working: `herdr
pane read <id> --source visible` showed real Claude Code TUI output
   (the interactive trust-folder dialog, with true-color styling) rendered
   through the wrapper, while its lifecycle events were observed separately
   on its own socket. OS ancestry in this arrangement is `herdr server` →
   pane shell → the wrapper → `claude` (the wrapper, not HerdR, is
   `claude`'s direct OS parent here).

# Sources

- <https://herdr.dev>
- <https://github.com/ogulcancelik/herdr> (source read at commit reviewed;
  local mirror: `~/Workspace/public-repos/github.com/ogulcancelik/herdr`)
- `herdr api schema --json` (bundled schema, protocol 22, schema_version 1)
- Homebrew formula `herdr` (`brew info herdr`)
