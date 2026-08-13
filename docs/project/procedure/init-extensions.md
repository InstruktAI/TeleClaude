---
description: 'TeleClaude-specific init extensions — help desk bootstrap and machine-global macOS install steps.'
visibility: 'public'
---

# Init Extensions — Procedure

## Goal

Document the TeleClaude-specific setup split: `telec projects init` owns project-local
plumbing and help desk bootstrap, while `make install` owns machine-global steps — the
logging runtime the host reads logs with, plus macOS launcher installation and
permission probing.

## Preconditions

- Running `telec projects init` from the TeleClaude project root for help desk bootstrap.
- Running `make install` from the TeleClaude project root for machine-global steps.
- For macOS machine-global steps: running on macOS (`sys.platform == "darwin"`).

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

### 4. Logging runtime wiring (`make install`)

`make install` provisions the machine's logging runtime alongside the other
machine-global tooling, before the macOS-specific steps.

- **Surface a conflicting entrypoint owner.** Before ensuring the package, the step
  reads the installed tool inventory to determine which package publishes the
  `instrukt-ai-logs` entrypoint. When a package other than `instruktai-python-logger`
  publishes it, the step warns loudly, naming that package and the remediation.
  TeleClaude never removes it. A conflict also makes the ensure call below fail, because
  the tool installer refuses to overwrite an entrypoint another package owns.
- **Ensure present and current.** `uv tool install --upgrade instruktai-python-logger`
  installs the package when it is absent and upgrades it to the latest release when it
  is behind, in one idempotent call. The step uses no presence check and no version
  comparison. The package carries no version constraint and is never pinned to
  TeleClaude's lockfile; it tracks latest.
- **Delegate the machine-level wiring.** `instrukt-ai-log-setup` is the logging
  package's own idempotent entrypoint. It writes the rotation configuration, installs
  the launchd agent or systemd timer, and reports the resolved log root and
  `status: healthy` on an already-wired host. TeleClaude invokes it and echoes its
  report rather than reimplementing that wiring.
- **A declined act warns; an unmet obligation fails.** A detected conflict warns and the
  install continues, and the ensure failure that follows it warns too. Every other
  failure to install, upgrade, or wire the runtime fails the install with a non-zero
  outcome naming the step.

The step is skipped in CI mode and in the deps-only install a git worktree resolves to.

Source: `bin/install.sh:install_log_runtime()`

## Outputs

- Help desk workspace scaffolded (TeleClaude project only).
- Launcher apps installed to `~/Applications/` by `make install` (macOS only).
- Permission probe results reported to the user by `make install` (macOS only).

- Logging runtime present, current, and wired by `make install`, with the resolved log
  root and health status reported to the user.

## Recovery

- All steps are idempotent. Re-running `telec projects init` repeats help desk bootstrap safely; re-running `make install` repeats macOS launcher/probe setup safely.
- If the help desk bootstrap fails, the main init continues unaffected.
- Permission denials require manual System Settings changes; re-running `make install`
  after granting access will show a passing probe.

- If the logging runtime step warns about a conflicting entrypoint owner, the install
  still completes and the runtime is left unwired. Remove the package that owns
  `instrukt-ai-logs` and re-run `make install`; the step is idempotent.
- If the logging runtime step fails the install for any other reason, resolve the
  reported cause — most often package-index reachability — and re-run `make install`.
