---
description: The PATH contract for TeleClaude agent shells and the daemon's own service environment — which tool directories are guaranteed, where the contract is implemented, and which sibling files must change together.
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
PATH-pin body (everything below the `TC_HOME=` line). They are deployed as
`~/.teleclaude/shell/.{zshenv,bashenv,profile}` (symlinks, via
`teleclaude/install/configure_agent_cli.py`) and selected by the
`teleclaude/install/wrappers/teleclaude-shell` entry wrapper, which sets
`ZDOTDIR`, `BASH_ENV`, and `ENV` so zsh, bash, and sh agents all land on them.
The wrapper itself does not build PATH — it only adds `~/.teleclaude/bin` and
execs the host shell; the guarantees live in the three env files.

Editing any one of the three requires editing all three identically. The body is
POSIX-sh so the same text is valid in zsh, bash, and sh.

### Implementation 2 — the daemon's own service PATH

The daemon runs direct subprocesses (e.g. blueprint regeneration calling
`graphify`) that **bypass the agent shells**, inheriting the daemon process PATH
set by its launchd/systemd unit. `bin/init/install_services.sh` generates that PATH — the launchd
`launchd_path` (macOS) and the systemd `Environment=PATH` / `service_path`
(Linux) — and includes the shared tool set (`~/.npm-global/bin`,
`~/.local/bin`, `~/.cargo/bin`).

## Known caveats

- The three env files are **live symlinks**: editing them takes effect for every
  new agent shell immediately, with no `make install`.
- The daemon unit PATH is **not** live: changing `bin/daemon-control.sh` requires
  `make install` (regenerate the unit) then `make restart` (reload the daemon).
- Inheritance is not a guarantee. An agent shell launched from a rich interactive
  login appears to "just work" because it inherits that PATH; the contract exists
  so it also works when launched from a narrow-PATH parent (e.g. directly under
  launchd).
