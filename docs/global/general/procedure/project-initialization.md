---
id: 'general/procedure/project-initialization'
type: 'procedure'
domain: 'general'
scope: 'global'
description: 'Complete telec init pipeline — agent CLI configuration, git plumbing, artifact sync, event domain seeding, file watchers, release channel, and optional AI enrichment.'
---

# Project Initialization — Procedure

## Goal

Bootstrap a project for TeleClaude by installing agent infrastructure, configuring git
plumbing, syncing artifacts, seeding event domains, installing file watchers, and
optionally generating AI-driven project documentation.

## Preconditions

- The project directory exists and contains source files (or is being initialized).
- `telec` CLI is available and the daemon is running.
- For enrichment: at least one agent is enabled and available for session dispatch.

## Steps

### 1. Configure agent CLIs

Installs the git safety wrapper, environment symlinks, and per-agent configuration
(Claude, Gemini, Codex). This is the global agent infrastructure — not project-specific.

Source: `teleclaude/install/configure_agent_cli.py:main()`

### 2. Ensure git repository

Initializes a git repo if the project is not already inside one. Uses `git init` as
a fallback.

Source: `teleclaude/project_setup/git_repo.py:ensure_git_repo()`

### 3. Install project git hooks

Copies hooks from the project-local `.githooks/` directory into `.git/hooks/`. If a
previous init set `core.hooksPath`, it is unset to restore `.git/hooks/` as the
active hooks directory (coexistence with pre-commit framework).

Source: `teleclaude/project_setup/git_repo.py:ensure_hooks_path()`

### 4. Configure git smudge/clean filters

Sets up the `teleclaude-docs` git filter that handles tilde expansion:

- **Smudge** (checkout): expands `@~/.teleclaude` to `@$HOME/.teleclaude`
- **Clean** (commit): converts absolute paths back to `@~/.teleclaude`

Re-checks out `docs/` and `agents/docs/` to apply the smudge filter to existing files.

Source: `teleclaude/project_setup/git_filters.py:setup_git_filters()`

### 5. Update .gitattributes

Adds filter patterns so that `docs/**/*.md` and `agents/docs/**/*.md` use the
`teleclaude-docs` filter. Idempotent — skips patterns already present.

Source: `teleclaude/project_setup/gitattributes.py:update_gitattributes()`

### 6. Install pre-commit hook

Detects the project's hook system (pre-commit framework, Husky, or raw git hooks)
and installs two guards:

- **Stash prevention guard**: blocks commits when the same file has both staged and
  unstaged changes, preventing pre-commit's stash/restore from corrupting the working tree.
- **Docs check**: rejects commits containing hardcoded HOME paths in `.md` files.

Source: `teleclaude/project_setup/hooks.py:install_precommit_hook()`

### 7. Sync project artifacts

Runs `telec sync` (warn-only mode) to build snippet indexes, inflate
`AGENTS.master.md` into `AGENTS.md`, and distribute artifacts to agent runtimes.

Source: `teleclaude/project_setup/sync.py:sync_project_artifacts()`

### 8. Seed event domains

Merges default event domain configurations into the global config
(`~/.teleclaude/teleclaude.yml`) under `event_domains.domains`. Idempotent — skips
if domains already have entries, preserving user customizations.

This step applies to every project because event domains are global infrastructure
that all projects share.

Source: `teleclaude/project_setup/domain_seeds.py:seed_event_domains()`

### 9. Install file watchers

Installs a platform-specific file watcher that triggers `telec sync` (or `telec watch`)
when docs, agents, or config files change:

- **macOS**: launchd plist under `~/Library/LaunchAgents/` with `KeepAlive` and
  `RunAtLoad`. Cleans up stale plists for the same project.
- **Linux**: systemd user path unit that monitors project directories and triggers a
  oneshot sync service.

Source: `teleclaude/project_setup/sync.py:install_docs_watch()`

### 10. Release channel enrollment (interactive)

Prompts for the deployment release channel (`alpha`/`beta`/`stable`) and persists the
choice to `teleclaude.yml` under `deployment.channel`. Stable channel requires a
`pinned_minor` version. Skipped in non-interactive (non-TTY) mode.

Source: `teleclaude/project_setup/init_flow.py:_prompt_release_channel()`

### 11. AI-driven project enrichment (interactive)

Detects whether the project already has `telec-init` generated snippets:

- **First init**: prompts "Run project analysis?"
- **Re-init**: prompts "Refresh project analysis?"

If accepted, launches a `/telec-init-analyze` session asynchronously via
`telec sessions run`. The analysis session follows the project analysis procedure
(`software-development/procedure/project-analysis`) and produces schema-valid doc
snippets under `docs/project/` per the scaffolding spec
(`software-development/spec/init-scaffolding`).

Skipped in non-interactive mode.

Source: `teleclaude/project_setup/init_flow.py:_offer_enrichment()`

## Outputs

- Agent hooks and wrappers installed globally.
- Git filters, `.gitattributes`, and pre-commit hooks configured for the project.
- Artifacts synced and indexes built.
- Event domains seeded in global config (if not already populated).
- File watcher installed for the project.
- Release channel persisted (interactive only).
- Enrichment session dispatched (interactive only, if accepted).

## Recovery

- `telec init` is idempotent. Re-running it is safe and will skip already-configured steps.
- If enrichment dispatch fails, the user is shown a manual command to retry:
  `telec sessions run --command /telec-init-analyze --project <root>`
- If sync reports findings, the init still completes because this step runs `telec sync --warn-only`; the findings are reported for follow-up.

## See Also

- ~/.teleclaude/docs/software-development/procedure/project-analysis.md
- ~/.teleclaude/docs/software-development/spec/init-scaffolding.md
- ~/.teleclaude/docs/general/procedure/company-onboarding.md
