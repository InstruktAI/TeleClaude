---
description: 'Launchd/systemd service templates must use replacement markers, never hardcoded paths.'
visibility: 'public'
---

# Launch Service Authoring — Policy

## Rules

- Service templates live in `templates/` and use `{{MARKER}}` double-brace placeholders for all environment-specific values.
- Templates must never contain hardcoded home directories, user-specific paths, or machine-specific binary locations.

- `bin/init/install_services.sh` resolves markers via `sed` substitution on every `make install`, renders the result to a temporary file, and writes it to `~/Library/LaunchAgents/` (macOS) or `/etc/systemd/system/` (Linux) only when that rendered content differs from the deployed definition. The unit is reloaded on the same condition, so an unchanged definition never disturbs its running service.

- Markers are resolved from runtime detection (`command -v`, `$HOME`, `$PROJECT_ROOT`), never from static strings.

### Standard markers

| Marker             | Resolved from                    | Example value                          |
| ------------------ | -------------------------------- | -------------------------------------- |
| `{{PYTHON_PATH}}`  | `$PROJECT_ROOT/.venv/bin/python` | `/home/user/project/.venv/bin/python`  |
| `{{UV_PATH}}`      | `command -v uv`                  | `/opt/homebrew/bin/uv`                 |
| `{{WORKING_DIR}}`  | `$PROJECT_ROOT` (repo root)      | `/home/user/project`                   |
| `{{PATH}}`         | Constructed from known bin dirs  | `/opt/homebrew/bin:/usr/local/bin:...` |
| `{{HOME}}`         | `$HOME`                          | `/home/user`                           |
| `{{LABEL}}`        | Service-specific label string    | `ai.instrukt.teleclaude.docs.watch`    |
| `{{COMMAND}}`      | Service-specific command         | `uv run --quiet ...`                   |
| `{{WATCH_PATHS}}`  | Constructed from project paths   | XML plist array entries                |
| `{{PROJECT_ROOT}}` | `$PROJECT_ROOT`                  | `/home/user/project`                   |
| `{{UNIT_ID}}`      | Systemd unit name                | `teleclaude-docs-watch`                |

### Adding a new service template

1. Create the template in `templates/` with markers for all paths.
2. Add an `install_launchd_<name>()` or `install_systemd_<name>()` function in `bin/init/install_services.sh` that resolves markers via `sed` and deploys through the shared content-gated helper, so the definition is written and reloaded only on a content difference.
3. Call the installer from `install_service()`.
4. Verify: `grep -r '/Users/\|/home/' templates/` must return nothing.

## Rationale

- Hardcoded paths break on different machines, different users, and when binaries move (e.g., uv migrating from `~/.local/bin` to `/opt/homebrew/bin`).
- Marker-based templates keep helper services resilient when binaries relocate (e.g., uv moving between `~/.local/bin` and `/opt/homebrew/bin`), so a host-installed unit keeps resolving its interpreter.

## Scope

- Applies to all files in `templates/`.

- Applies to all installer functions in `bin/init/install_services.sh` that process templates.

## Enforcement

- The `hardcoded-home-path` guardrail in `tools/lint/guardrails.py` scans `templates/` (and all source dirs) for the current user's home path at pre-commit time.
- Any match fails the commit unless marked with `guard: allow-home-path`.

## Exceptions

- None.
