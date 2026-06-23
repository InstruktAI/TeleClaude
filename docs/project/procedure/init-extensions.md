---
description: 'TeleClaude-specific init extensions — help desk bootstrap and machine-global macOS install steps.'
visibility: 'public'
---

# Init Extensions — Procedure

## Goal

Document the TeleClaude-specific setup split: `telec projects init` owns project-local
plumbing and help desk bootstrap, while `make install` owns machine-global macOS
launcher installation and permission probing.

## Preconditions

- Running `telec projects init` from the TeleClaude project root for help desk bootstrap.
- Running `make install` from the TeleClaude project root for macOS machine-global steps.
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

### 2. macOS launcher installation (`make install`)

Copies launcher `.app` bundles from `bin/` into `~/Applications/`:

- `TmuxLauncher.app` — wrapper that gives tmux sessions macOS permission inheritance
- `ClaudeLauncher.app`, `GeminiLauncher.app`, `CodexLauncher.app` — per-agent launchers

Existing bundles in `~/Applications/` are replaced. Build step is skipped by default
(uses committed bundles).

Source: `teleclaude/project_setup/macos_setup.py:install_launchers()`

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

## Outputs

- Help desk workspace scaffolded (TeleClaude project only).
- Launcher apps installed to `~/Applications/` by `make install` (macOS only).
- Permission probe results reported to the user by `make install` (macOS only).

## Recovery

- All steps are idempotent. Re-running `telec projects init` repeats help desk bootstrap safely; re-running `make install` repeats macOS launcher/probe setup safely.
- If the help desk bootstrap fails, the main init continues unaffected.
- Permission denials require manual System Settings changes; re-running `make install`
  after granting access will show a passing probe.
