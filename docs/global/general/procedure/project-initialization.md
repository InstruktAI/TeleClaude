---
description: 'Complete telec projects init pipeline — project git plumbing, artifact sync, event domain seeding, project registration, release channel.'
visibility: 'public'
---

# Project Initialization — Procedure

## Goal

Bootstrap a project for TeleClaude by configuring project git plumbing, syncing
artifacts, seeding event domains, and registering the project root. Machine-global
agent infrastructure is installed by the TeleClaude checkout's `make install`.

AI-driven project analysis and quality-config assessment are a separate, user-invoked
step — see the project-onboarding procedure (`general/procedure/project-onboarding`).

## Preconditions

- The project directory exists and contains source files (or is being initialized).
- `telec` CLI is available and the daemon is running.

## Steps

### 1. Ensure git repository

Initializes a git repo if the project is not already inside one. Uses `git init` as
a fallback.

Source: `teleclaude/project_setup/git_repo.py:ensure_git_repo()`

### 2. Install project git hooks

Copies hooks from the project-local `.githooks/` directory into `.git/hooks/`. If a
previous init set `core.hooksPath`, it is unset to restore `.git/hooks/` as the
active hooks directory (coexistence with pre-commit framework).

Source: `teleclaude/project_setup/git_repo.py:ensure_hooks_path()`

### 3. Configure git smudge/clean filters

Sets up the `teleclaude-docs` git filter that handles tilde expansion:

- **Smudge** (checkout): expands `@~/.teleclaude` to `@$HOME/.teleclaude`
- **Clean** (commit): converts absolute paths back to `@~/.teleclaude`

Re-checks out `docs/` and `agents/docs/` to apply the smudge filter to existing files.

Source: `teleclaude/project_setup/git_filters.py:setup_git_filters()`

### 4. Update .gitattributes

Adds filter patterns so that `docs/**/*.md` and `agents/docs/**/*.md` use the
`teleclaude-docs` filter. Idempotent — skips patterns already present.

Source: `teleclaude/project_setup/gitattributes.py:update_gitattributes()`

### 5. Install pre-commit hook

Detects the project's hook system (pre-commit framework, Husky, or raw git hooks)
and installs two guards:

- **Stash prevention guard**: blocks commits when the same file has both staged and
  unstaged changes, preventing pre-commit's stash/restore from corrupting the working tree.
- **Docs check**: rejects commits containing hardcoded HOME paths in `.md` files.

Source: `teleclaude/project_setup/hooks.py:install_precommit_hook()`

### 6. Sync project artifacts

Runs the bootstrap sync — validation runs and reports findings without blocking — to build
snippet indexes, inflate `AGENTS.master.md` into `AGENTS.md`, and distribute artifacts to
agent runtimes.

This step happens before slug persistence because `sync_project_artifacts()`
materializes a bare `teleclaude.yml` for fresh projects. `telec projects init` then
rewrites that file in place to guarantee `project_slug` exists before the
project is registered.

Source: `teleclaude/project_setup/sync.py:sync_project_artifacts()`

### 7. Ensure `project_slug` and register the project root

Reads `teleclaude.yml`, ensures `project_slug` is set (deriving one from
`project_name` or the directory name via `normalize_slug` when missing or
invalid), and writes it back in place using comment-preserving YAML. Then
appends the absolute project root to `~/.teleclaude/projects.yaml`
idempotently.

`telec projects init` is the **sole** writer of the project registry. `telec sync`
must not mutate `~/.teleclaude/projects.yaml`. Once registered, the project
is visible to `ProjectCatalogService` and every consumer that iterates
projects (docs cross-project namespace, job orchestration, etc.).

Source: `teleclaude/project_setup/init_flow.py:_ensure_project_slug()`
and `teleclaude/project_manifest.py:register_root()`

### 8. Seed event domains

Merges default event domain configurations into the global config
(`~/.teleclaude/teleclaude.yml`) under `event_domains.domains`. Idempotent — skips
if domains already have entries, preserving user customizations.

This step applies to every project because event domains are global infrastructure
that all projects share.

Source: `teleclaude/project_setup/domain_seeds.py:seed_event_domains()`

### 9. Watcher ownership

`telec projects init` does **not** install watchers. It registers the project root in
`~/.teleclaude/projects.yaml`. Machine-global setup is installed by `make install`,
and service startup/install is owned by `make start`; the global watcher reads this
manifest to decide which projects to watch and sync surgically.

Source: `teleclaude/project_manifest.py:register_root()`

### 10. Release channel enrollment (interactive)

Prompts for the deployment release channel (`alpha`/`beta`/`stable`) and persists the
choice to `teleclaude.yml` under `deployment.channel`. Stable channel requires a
`pinned_minor` version. Skipped in non-interactive (non-TTY) mode.

Source: `teleclaude/project_setup/init_flow.py:_prompt_release_channel()`

## Outputs

- Git filters, `.gitattributes`, and pre-commit hooks configured for the project.
- `project_slug` persisted in `teleclaude.yml` and project root registered in `~/.teleclaude/projects.yaml`.
- Artifacts synced and indexes built.
- Event domains seeded in global config (if not already populated).
- Release channel persisted (interactive only).

## Recovery

- `telec projects init` is idempotent. Re-running it is safe and will skip already-configured steps.
- The bootstrap sync reports validation findings without blocking, so init always completes even when a project already carries findings; the commit gate validates once real work begins.

## See Also

- ~/.teleclaude/docs/general/procedure/project-onboarding.md
- ~/.teleclaude/docs/software-development/procedure/project-analysis.md
- ~/.teleclaude/docs/software-development/spec/init-scaffolding.md
- ~/.teleclaude/docs/general/procedure/company-onboarding.md
