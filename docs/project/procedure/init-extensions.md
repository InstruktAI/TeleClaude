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

<!-- planned:ensure-project-remote -->

### 1a. Project remote provisioning

After the project's git repository and canonical `project_slug` are established,
init ensures the project has a git `origin` remote so deliberately set-up
projects preserve work remotely and participate in the distributed todo-handoff
model. This is a quality enrichment for projects set up via `telec projects
init` (and `telec projects onboard`, which wraps it); bare folders that never
run init are never touched and keep working with local-only todos.

Behavior:

- **Idempotent.** If an `origin` remote already exists, the step does nothing.
- **Target derivation.** The target repository is `<git_org>/<project_slug>` on
  `<git_host>`, drawn from the global company profile (see
  `project/spec/feature/config/company-profile`) and the project's
  `project_slug`. When no company profile (or no `git_org`) is configured, the
  step skips and the project stays local-only.
- **Prefer automation.** When the GitHub CLI `gh` is available and
  authenticated for the host, the repository is created automatically and the
  `origin` remote is added.
- **Human fallback with a link.** When auto-creation is not possible (no `gh`,
  not authenticated, or a non-GitHub host) and the session is interactive, the
  user is shown the organization URL and the proposed repository name, asked to
  create the repository, and on confirmation the remote is added and verified to
  resolve.
- **Never blocks setup.** If the user declines, the session is non-interactive
  (no TTY, e.g. CI), or the remote cannot be established, init completes and the
  project stays local-only. The enrichment offers; it does not gate.

Source: `teleclaude/project_setup/init_flow.py:init_project()` (the
`ensure_remote` step).

<!-- /planned:ensure-project-remote -->

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
