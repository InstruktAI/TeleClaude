---
description: The PATH, terminal-hint, and XDG session-environment contract for TeleClaude agent shells and the daemon's own service environment — which tool directories and TUI color hints are guaranteed, where the contract is implemented, and which sibling files must change together.
---

# Agent Shell PATH — Spec

## What it is

Agents and the daemon shell out to platform-published binaries (`graphify`,
`telec`) and language toolchains (`cargo`) by **bare name**. Those binaries are
not in the system default PATH — `make install` publishes them under
`~/.local/bin` (and rust under `~/.cargo/bin`). For bare-name invocation to
resolve, every execution context the platform controls must guarantee those
directories on PATH, independent of whatever PATH the launching context happened
to provide.

There are two such contexts, with two separate implementations of the same
contract. A change to the guaranteed set must be reflected in **both**.

## Canonical fields

### Guaranteed directories

The shared tool set is guaranteed in **both** execution contexts, since both
shell out to these by bare name:

- `~/.local/bin` — platform-published binaries (`graphify`, `telec`).
- `~/.cargo/bin` — rust toolchain (rust is a first-class platform language).
- `~/.npm-global/bin` — npm-global installs (`node`, `npm`, and the `dsh`
  DeepSeek Harness CLI, whose shim is `#!/usr/bin/env node`).

Each is added only when present and their relative order is not load-bearing.

One directory is **agent-shell only**:

- `$TELECLAUDE_HOME/bin` (default `~/.teleclaude/bin`) — force-pinned to the
  front so the agent-session git wrapper wins over the real `git`. The daemon
  does not add it: its git calls resolve absolutely, and it does not use the
  wrapper.

### Implementation 1 — agent shells

`teleclaude/install/shell/{zshenv,bashenv,profile}` each carry a **byte-identical**
body (everything below the `TC_HOME=` line): the PATH-pin block followed by the
terminal-hints block. They are deployed as
`~/.teleclaude/shell/.{zshenv,bashenv,profile}` (symlinks, via
`teleclaude/install/configure_agent_cli.py`) and selected by the
`teleclaude/install/wrappers/teleclaude-shell` entry wrapper, which sets
`ZDOTDIR`, `BASH_ENV`, and `ENV` so zsh, bash, and sh agents all land on them.
The wrapper itself does not build PATH — it only adds `~/.teleclaude/bin` and
execs the host shell; the guarantees live in the three env files.

Editing any one of the three requires editing all three identically. The body is
POSIX-sh so the same text is valid in zsh, bash, and sh.

<!-- planned:issue-129 -->

#### Bound-session GitHub command routing

When the daemon creates a session whose persisted binding has both a GitHub
actor and target, its per-session PATH places a private command directory under
that session's existing `$TMPDIR` ahead of the shared tool directories. The
`gh` entry there invokes the Python facade defined by
`local/projects/teleclaude/spec/feature/integration/github-posting`; the facade
uses GitHubKit and has no provider-CLI fallback. Its command grammar, operation
admission and fresh caller checks remain with the identity and posting owners.

The private directory is scoped to that session and comes before
`$TELECLAUDE_HOME/bin`, leaving the shared agent-session git wrapper in its
existing position. Sessions without the persisted GitHub actor-and-target
binding, including local-backend sessions, receive no `gh` override and keep
their current PATH resolution. The routing choice comes from the daemon's
persisted session binding, not a command argument or agent-supplied environment
value. It selects a command entrypoint but supplies no authentication or
provider authority; the facade rechecks those facts for each call.
<!-- /planned:issue-129 -->

#### Terminal hints

The terminal-hints block exports two static hints for agent TUIs:

- `COLORTERM=truecolor` — advertises 24-bit color support to agent CLIs
  (Gemini, Claude, Codex, dsh).
- `CLAUDE_CODE_TMUX_TRUECOLOR=1` — the tmux-truecolor hatch read by
  `@deepseek-harness-tui/dsh-tui` and Claude Code. Without it those TUIs clamp
  chalk from truecolor to 256-color whenever `$TMUX` is set; the pane attach
  sets `Tc`/`RGB` terminal-overrides, so truecolor passes through and the
  clamp must not fire.

Both hints reach every agent pane regardless of host shell: the wrapper's
fallback (`exec sh`) still reads `ENV`/`.profile`.

### Implementation 2 — the daemon's own service PATH

The daemon runs direct subprocesses (e.g. blueprint regeneration calling
`graphify`) that **bypass the agent shells**, inheriting the daemon process PATH
set by its launchd/systemd unit. `bin/init/install_services.sh` generates that PATH — the launchd
`launchd_path` (macOS) and the systemd `Environment=PATH` / `service_path`
(Linux) — and includes the shared tool set (`~/.npm-global/bin`,
`~/.local/bin`, `~/.cargo/bin`).

### XDG base directories

The daemon resolves two XDG base directories — `XDG_DATA_HOME` and
`XDG_CACHE_HOME` — from the user's login shell through the same capture that
resolves PATH, and places them in every agent session's environment. Tools that
honour either name — the pnpm store, uv, agent CLI caches — therefore resolve the
same directory inside an agent session as they do in the user's own shells. A
name the login shell does not declare falls back to the daemon process
environment's value for that name, and is absent from the session when neither
declares it. The remaining XDG names are not captured.

These values arrive in the session's inherited environment. Provenance for
environment values that no `.env` layer may carry is owned by
`local/projects/teleclaude/spec/feature/config/agent-env-allow-list`.

## Known caveats

- The three env files are **live symlinks**: editing them takes effect for every
  new agent shell immediately, with no `make install`.
- XDG capture follows the user's login shell: an edit to that shell's
  configuration applies to the next agent session, with no `make install` and no
  daemon restart.
- The daemon unit PATH is **not** live: changing `bin/daemon-control.sh` requires
  `make install` (regenerate the unit) then `make restart` (reload the daemon).
- Inheritance is not a guarantee. An agent shell launched from a rich interactive
  login appears to "just work" because it inherits that PATH; the contract exists
  so it also works when launched from a narrow-PATH parent (e.g. directly under
  launchd).
