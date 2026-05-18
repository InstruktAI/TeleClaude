---
description: 'TeleClaude-specific init extensions — help desk bootstrap and macOS launcher installation with permissions probe.'
domain: 'software-development'
id: 'project/procedure/init-extensions'
scope: 'project'
type: 'procedure'
visibility: 'public'
---

# Init Extensions — Procedure

## Goal

Document the `telec projects init` steps that apply only to the TeleClaude project itself,
beyond the universal project initialization pipeline.

## Preconditions

- Running `telec projects init` from the TeleClaude project root (detected by the presence
  of `teleclaude/project_setup/init_flow.py`).
- For macOS steps: running on macOS (`sys.platform == "darwin"`).

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

### 2. macOS launcher installation

Copies launcher `.app` bundles from `bin/` into `~/Applications/`:

- `TmuxLauncher.app` — wrapper that gives tmux sessions macOS permission inheritance
- `ClaudeLauncher.app`, `GeminiLauncher.app`, `CodexLauncher.app` — per-agent launchers

Existing bundles in `~/Applications/` are replaced. Build step is skipped by default
(uses committed bundles).

Source: `teleclaude/project_setup/macos_setup.py:install_launchers()`

### 3. macOS permissions probe

After launcher installation, runs an end-of-init permission probe via the tmux
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
- Launcher apps installed to `~/Applications/` (macOS only).
- Permission probe results reported to the user (macOS only).

## Recovery

- All steps are idempotent. Re-running `telec projects init` repeats the probe safely.
- If the help desk bootstrap fails, the main init continues unaffected.
- Permission denials require manual System Settings changes; re-running init
  after granting access will show a passing probe.
