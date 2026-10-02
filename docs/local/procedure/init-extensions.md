---
description: 'TeleClaude-specific init extensions — project-local init boundaries and machine-global macOS install steps.'
visibility: 'public'
---

# Init Extensions — Procedure

## Goal

Document the TeleClaude-specific setup split: `telec config project init` owns project-local
plumbing, while `make install` owns machine-global steps — the
logging runtime the host reads logs with, plus macOS launcher installation and
permission probing.

## Preconditions

- Running `make install` from the TeleClaude project root for machine-global steps.
- For macOS machine-global steps: running on macOS (`sys.platform == "darwin"`).

## Steps

### 1a. Project remote provisioning — an agent procedure, not an init step

`telec config project init` does **not** provision a git remote. It establishes the
local repository and the canonical `project_slug` only; there is no
`ensure_remote` code step branching on `gh`-availability, authentication, or TTY.

Remote provisioning is an **agent procedure** run during project onboarding. The
agent resolves the project's company (the active project's `company:` field → the
company profile's `git` org; see `local/projects/teleclaude/spec/domain/config`), derives
`<org>/<project_slug>`, and establishes `origin` by judgment — `gh repo create`
when it can, otherwise handing the org link to the human conversationally — then
`git remote add origin` (idempotent; skip when `origin` already exists). The
agent handles authentication, interactivity, and confirmation as judgment, not
code branches. A project with no company resolves no org and stays local-only;
remote setup never gates project setup.

### 1b. Project initialization installs plumbing but does not publish

`telec config project init` materializes the declaration and converges the project's
filters and hooks. It does not publish documentation or agent artifacts from
the setup working tree. The first canonical commit activates those sources
through commit maintenance, and `telec sync` from the project's home directory
publishes its committed state at any time; neither deploys the working tree.

### 2. macOS launcher build (`make launchers`) and installation (`make install`)

A dedicated `make launchers` target compiles the `.app` bundles from one parameterized
wrapper source and signs them into `bin/`. The bundles are gitignored build outputs, so
a fresh checkout has none. `make install`, including the install post-commit
maintenance runs, and the channel updater's install stage reach the same builder, which
rebuilds only when the launcher code identity contract calls for it and otherwise
leaves `~/Applications/` untouched. Every route compiles and signs through that one
builder:

- `TmuxLauncher.app` — wrapper that gives tmux sessions macOS permission inheritance
- `ClaudeLauncher.app`, `CodexLauncher.app`, `GeminiLauncher.app` — per-agent launchers

Each wrapper spawns its target as a child process and waits for it rather than
replacing its own process image, so the bundle identity macOS attributes file
access to is the wrapper's own. `ClaudeLauncher` and `CodexLauncher` target the
`claude` and `codex` binaries; `GeminiLauncher` targets `agy`. Building requires
the Xcode Command Line Tools; absent the Swift compiler `make launchers` fails with the
`xcode-select --install` remedy and produces no bundle. Installing on macOS refuses to
start when that compiler is missing, so the remedy is stated before any work begins
rather than at the launcher step.

Each bundle is signed for a stable code identity that survives rebuilds
(`sdlc/procedure/macos-stable-code-signing`). What signing guarantees — a machine-local
authority in a dedicated keychain, unattended and bounded runs, verification before any
installed bundle is replaced, and when a re-grant is owed — is the contract of
`local/projects/teleclaude/spec/feature/reconciliation/launcher-code-identity`; the
operation that converges it is owned by `local/projects/teleclaude/spec/domain/reconciliation`.

Its output names the authority it signed with and says whether it created that authority
or found nothing to rebuild; a failure states its cause and remedy and fails the step that
invoked it. `make launchers-renew-authority` is the only route that discards an authority,
and it states that every launcher grant dies with it.

When install names launchers whose Full Disk Access must be granted again, remove each
stale entry under System Settings › Privacy & Security › Full Disk Access and add the
bundle again at that machine's screen; a recovery session cannot make that grant.

Source: `teleclaude/core/reconciliation/launcher_identity.py` (decisions and result),
`teleclaude/project_setup/launcher_signing.py` (keychain, signing and compile effects),
`teleclaude/project_setup/macos_setup.py:install_launchers()` (verified replacement),
`teleclaude/install/launcher_identity.py` (entry point for install, `make launchers` and renewal)

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

If denials are detected, `make install` closes with the grant as a named remaining
step: each launcher bundle's path, and the instruction to remove a stale entry before
re-adding it, since a row left in place keeps presenting as enabled.

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

### 5. Configuration-schema publication (`make install`)

`make install` publishes every configuration schema into the TeleClaude home
before converging this checkout's plumbing. The act and its guarantees are
`local/projects/teleclaude/spec/feature/reconciliation/config-schema-publication`. The step is
skipped in CI mode and in the deps-only install a git worktree resolves to.

Source: `teleclaude/core/reconciliation/config_schemas.py`

<!-- planned:startable-unattended-install -->
### 6. Fresh-machine bootstrap (`make install`)

`make install` leaves a fresh machine startable, owned and serving its published
documentation, with or without a person present. The guarantees are
`local/projects/teleclaude/spec/feature/reconciliation/fresh-machine-bootstrap`. The decision
boundary is in `local/projects/teleclaude/spec/domain/reconciliation`.

- **Unattended runs.** A run without a terminal never waits for a person. Provide
  the owner seed up front. A step that needs input it was not given fails at once
  and names the input.
- **Owner.** While no person is registered, installation registers the seeded
  person as platform administrator, or asks the operator at a terminal for one. A
  seed that conflicts with the registered people fails the install and changes
  nobody.
- **Environment.** Installation writes the checkout's environment file with local
  defaults only when none exists. Integrations are added afterwards through
  `telec config wizard`.
- **Publication.** Installation publishes the checkout's committed `main` tip. When
  it publishes nothing, it says why. A home that was skipped or failed to build
  recovers with `telec sync` from the checkout once the cause is fixed. A checkout
  with no local `main` has nothing publication can read, so `telec sync` cannot
  help it.
- **Optional apps.** LM Studio, its llmster service and Handy are installed only
  when chosen at a terminal.

<!-- /planned:startable-unattended-install -->
## Outputs

- Launcher apps installed to `~/Applications/` by `make install` (macOS only).
- Permission probe results reported to the user by `make install` (macOS only).

- Logging runtime present, current, and wired by `make install`, with the resolved log
  root and health status reported to the user.
- Configuration schemas published into the TeleClaude home by `make install`.
<!-- planned:startable-unattended-install -->
- A startable checkout, a registered first administrator and the checkout's
  committed documentation published into the home, from `make install`, with or
  without a person present.
<!-- /planned:startable-unattended-install -->

## Recovery

- All steps are idempotent. Re-running `make install` repeats macOS launcher/probe setup safely.
- Permission denials require manual System Settings changes; re-running `make install`
  after granting access will show a passing probe.

- If the logging runtime step warns about a conflicting entrypoint owner, the install
  still completes and the runtime is left unwired. Remove the package that owns
  `instrukt-ai-logs` and re-run `make install`; the step is idempotent.
- If the logging runtime step fails the install for any other reason, resolve the
  reported cause — most often package-index reachability — and re-run `make install`.
