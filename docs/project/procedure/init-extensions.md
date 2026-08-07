---
description: 'TeleClaude-specific init extensions — help desk bootstrap and machine-global macOS install steps.'
visibility: 'public'
---

# Init Extensions — Procedure

## Goal

<!-- planned-change:make-install-delegates-log-runtime-wiring -->

Document the TeleClaude-specific setup split: `telec projects init` owns project-local
plumbing and help desk bootstrap, while `make install` owns machine-global macOS
launcher installation and permission probing.

## Preconditions

- Running `telec projects init` from the TeleClaude project root for help desk bootstrap.
- Running `make install` from the TeleClaude project root for macOS machine-global steps.
- For macOS machine-global steps: running on macOS (`sys.platform == "darwin"`).

<!-- change:make-install-delegates-log-runtime-wiring -->

Document the TeleClaude-specific setup split: `telec projects init` owns project-local
plumbing and help desk bootstrap, while `make install` owns machine-global steps — the
logging runtime the host reads logs with, plus macOS launcher installation and
permission probing.

## Preconditions

- Running `telec projects init` from the TeleClaude project root for help desk bootstrap.
- Running `make install` from the TeleClaude project root for machine-global steps.
- For macOS machine-global steps: running on macOS (`sys.platform == "darwin"`).

<!-- /planned-change:make-install-delegates-log-runtime-wiring -->

## Steps

### 1. Help desk workspace bootstrap

When init detects it is running inside the TeleClaude project, it scaffolds the
help desk workspace. The help desk directory is resolved from
`config.computer.help_desk_dir` or defaults to a sibling directory
(`../help-desk` relative to the TeleClaude project root).

Idempotent — skips if the directory already exists. Copies templates and
re-runs `telec projects init` within the help desk project to bootstrap its own
plumbing.

Source: `teleclaude/project_setup/help_desk_bootstrap.py:bootstrap_help_desk()`

### 1a. Project remote provisioning — an agent procedure, not an init step

`telec projects init` does **not** provision a git remote. It establishes the
local repository and the canonical `project_slug` only; there is no
`ensure_remote` code step branching on `gh`-availability, authentication, or TTY.

Remote provisioning is an **agent procedure** run during project onboarding. The
agent resolves the project's company (the active project's `company:` field → the
company profile's `git` org; see `project/spec/domain/config`), derives
`<org>/<project_slug>`, and establishes `origin` by judgment — `gh repo create`
when it can, otherwise handing the org link to the human conversationally — then
`git remote add origin` (idempotent; skip when `origin` already exists). The
agent handles authentication, interactivity, and confirmation as judgment, not
code branches. A project with no company resolves no org and stays local-only;
remote setup never gates project setup.

### 2. macOS launcher build (`make launchers`) and installation (`make install`)

A dedicated `make launchers` target compiles the `.app` bundles from one parameterized
wrapper source and signs them into `bin/`. It is the only entry point that compiles or
signs. `make install` copies the pre-built `bin/*.app` bundles into `~/Applications/`,
replacing existing bundles, and never compiles — a missing bundle fails the install step
naming `make launchers`:

- `TmuxLauncher.app` — wrapper that gives tmux sessions macOS permission inheritance
- `ClaudeLauncher.app`, `CodexLauncher.app`, `GeminiLauncher.app` — per-agent launchers

Each wrapper spawns its target as a child process and waits for it rather than
replacing its own process image, so the bundle identity macOS attributes file
access to is the wrapper's own. `ClaudeLauncher` and `CodexLauncher` target the
`claude` and `codex` binaries; `GeminiLauncher` targets `agy`. Building requires
the Xcode Command Line Tools; absent the Swift compiler `make launchers` fails with the
`xcode-select --install` remedy and produces no bundle.

Each bundle is signed for a stable code identity that survives rebuilds, per
`software-development/procedure/macos-stable-code-signing`: one shared machine-local
signing authority with a per-executable identifier, so Full Disk Access grants keep
matching after a recompile.

Source: `teleclaude/project_setup/macos_setup.py:install_launchers()` (install/copy),
`src/Launcher/build.sh` via the `make launchers` target (build/sign)

### 2a. macOS tmux server service (`make install`)

Installs and loads the `ai.instrukt.tmux-server` launch agent after the launcher
bundles are present. The job runs `TmuxLauncher.app` in foreground-server mode,
uses the TeleClaude home directory as its stable working directory, and is kept
alive by launchd. Ordinary launcher invocations are client-only, so another
process cannot recreate the tmux server from an ambient project or disposable
worktree directory.

An already-running tmux server remains available during installation. The newly
loaded launch agent takes ownership when that server is intentionally stopped;
launchd then recreates it from the stable working directory.

Source: `teleclaude/project_setup/macos_setup.py:install_tmux_server_service()`

### 3. macOS permissions probe (`make install`)

After launcher installation, `make install` runs a permission probe via the tmux
launcher to trigger macOS permission dialogs for protected paths:

- `~/Library/Messages/chat.db`
- `~/Library/Safari/History.db`
- `~/Library/Mail`
- `~/Library/CloudStorage`

The probe runs inside a temporary tmux session (`tc_perm_probe`) so that the
launcher binary — not Python directly — is the process requesting access. This
is essential because macOS grants Full Disk Access per-binary, and agents run
through the tmux launcher.

If denials are detected, the user is instructed to enable Full Disk Access for
the launcher apps in System Settings.

Source: `teleclaude/project_setup/macos_setup.py:run_permissions_probe()`

<!-- planned:make-install-delegates-log-runtime-wiring -->

### 4. Logging runtime wiring (`make install`)

`make install` provisions the machine's logging runtime alongside the other
machine-global tooling, before the macOS-specific steps. The InstruktAI logging CLI
is the reader every application on the host queries its logs with, so the writer the
daemon logs through and the reader an operator reads with must not drift apart.

- **Ensure present and current.** `uv tool install --upgrade instruktai-python-logger`
  installs the package when it is absent and upgrades it to the latest release when it
  is behind, in one idempotent call. A presence check is deliberately not used: an
  outdated package passes it, and that drift persists silently for as long as nobody
  reinstalls. The package is equally deliberately not pinned to TeleClaude's lockfile —
  the CLI is shared infrastructure other applications read their logs with, and pinning
  it would make a TeleClaude upgrade move a tool TeleClaude does not own. It tracks
  latest, which is safe because the CLI is backward-compatible on read.
- **Delegate the machine-level wiring.** `instrukt-ai-log-setup` is the logging
  package's own idempotent entrypoint. It writes the rotation configuration, installs
  the launchd agent or systemd timer, and reports the resolved log root and
  `status: healthy` on an already-wired host. TeleClaude invokes it and echoes its
  report rather than reimplementing that wiring.
- **Surface a conflicting entrypoint owner.** A different package can own the shared
  `instrukt-ai-logs` entrypoint — a legacy logger package resolving a pre-migration log
  root satisfies any presence check while reading a dead tree. Before ensuring the
  package, the step inspects the installed tool inventory and warns loudly when a
  package other than `instruktai-python-logger` provides that entrypoint, naming the
  package and the remediation. TeleClaude never removes it: that package is
  machine-global state TeleClaude does not own and other applications may depend on it.
  Such a conflict also makes the ensure call itself fail, because the tool installer
  refuses to overwrite an entrypoint another package owns.
- **A declined act warns; an unmet obligation fails.** The two failure shapes are not
  the same and are not treated the same. A detected conflict is TeleClaude deliberately
  declining to act on state it does not own, so it warns and the install continues —
  failing there would leave a host permanently uninstallable over a condition TeleClaude
  has chosen not to fix, and the subsequent ensure failure is that same declined act
  reported twice. Any other failure to install, upgrade, or wire the runtime is an
  obligation `make install` accepted and did not meet: it fails the install with a
  non-zero outcome naming the step. Reporting a successful install while the runtime it
  promised is absent, stale, or unwired is the silent failure this step exists to
  prevent, and the operator's very next action is to read logs through it.

The step is skipped in CI mode and in the deps-only install a git worktree resolves to,
because neither owns machine-global state.

Source: `bin/install.sh:install_log_runtime()`

<!-- /planned:make-install-delegates-log-runtime-wiring -->

## Outputs

- Help desk workspace scaffolded (TeleClaude project only).
- Launcher apps installed to `~/Applications/` by `make install` (macOS only).
- Permission probe results reported to the user by `make install` (macOS only).

<!-- planned:make-install-delegates-log-runtime-wiring -->

- Logging runtime present, current, and wired by `make install`, with the resolved log
  root and health status reported to the user.

<!-- /planned:make-install-delegates-log-runtime-wiring -->

## Recovery

- All steps are idempotent. Re-running `telec projects init` repeats help desk bootstrap safely; re-running `make install` repeats macOS launcher/probe setup safely.
- If the help desk bootstrap fails, the main init continues unaffected.
- Permission denials require manual System Settings changes; re-running `make install`
  after granting access will show a passing probe.

<!-- planned:make-install-delegates-log-runtime-wiring -->

- If the logging runtime step warns about a conflicting entrypoint owner, the install
  still completes and the runtime is left unwired. Remove the package that owns
  `instrukt-ai-logs` and re-run `make install`; the step is idempotent.
- If the logging runtime step fails the install for any other reason, resolve the
  reported cause — most often package-index reachability — and re-run `make install`.

<!-- /planned:make-install-delegates-log-runtime-wiring -->
