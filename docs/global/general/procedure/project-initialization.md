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

### 2. Declare the project's capability subscriptions

Establishes the project config marker, then infers any capability block the manifest
does not already declare from durable repository structure: a `Makefile` or a
recognized language tree implies `code`, authored snippet frontmatter under `docs/`
implies `docs`, and files under `agents/` or `.agents/` imply `agents`. Only missing
blocks are materialized — an explicit declaration is preserved, never overwritten.
The resolved subscriptions are then projected as markers under the repository's
common git directory, where the installed shell plumbing reads them by existence
check.

This step runs before any capability-gated step below, so a project receives only the
plumbing it subscribes to. Everything downstream reads the declaration; nothing
re-infers from repository shape at runtime.

Source: `teleclaude/project_setup/init_flow.py:_declare_inferred_capabilities()`
and `teleclaude/project_setup/capability_markers.py:project_capabilities()`

### 3. Configure git smudge/clean filters (`docs` only)

Sets up the `teleclaude-docs` git filter that handles tilde expansion:

- **Smudge** (checkout): expands `@~/.teleclaude` to `@$HOME/.teleclaude`
- **Clean** (commit): converts absolute paths back to `@~/.teleclaude`

Re-checks out `docs/` and `agents/docs/` to apply the smudge filter to existing files.

A project that does not subscribe `docs` gets no filter driver.

Source: `teleclaude/project_setup/git_filters.py:setup_git_filters()`

### 4. Update .gitattributes (`docs` only)

Adds filter patterns so that `docs/**/*.md` and `agents/docs/**/*.md` use the
`teleclaude-docs` filter. Idempotent — skips patterns already present. This is the
one project-tracked file TeleClaude writes, and it is written additively at adoption
only; no later capability change edits it.

Source: `teleclaude/project_setup/gitattributes.py:update_gitattributes()`

### 5. Sync project artifacts

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

Runs the bootstrap sync — validation runs and reports findings without blocking — to build
snippet indexes, inflate `AGENTS.master.md` into `AGENTS.md`, and distribute artifacts to
agent runtimes.
<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

Runs bootstrap synchronization. Validation reports findings without blocking, then the
initializer's internal deployment builds snippet indexes, inflates `AGENTS.master.md` into
`AGENTS.md`, and distributes artifacts to agent runtimes.
<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

This step happens before slug persistence because `sync_project_artifacts()`
materializes a bare `teleclaude.yml` for fresh projects. `telec projects init` then
rewrites that file in place to guarantee `project_slug` exists before the
project is registered.

Source: `teleclaude/project_setup/sync.py:sync_project_artifacts()`

### 6. Install code plumbing (`code` only)

Deploys the quality skeleton (downstream projects only) and installs the
TeleClaude-owned `pre-commit`, `post-merge`, and `pre-push` hooks into `.git/hooks/`
from the canonical sources under `templates/quality/githooks/`. The hooks are
language-neutral, so any code project receives the same set regardless of language.

Installation goes through a provenance-aware seam: a hook the project authored itself
is preserved, and a stale `core.hooksPath` from an earlier init is unset so
`.git/hooks/` is the active directory again.

A project that does not subscribe `code` — a data or documentation repository —
receives no hooks and no skeleton.

Source: `teleclaude/project_setup/hooks.py:install_code_hooks()`
and `teleclaude/project_setup/skeleton.py:deploy_skeleton()`

### 7. Ensure `project_slug` and register the project root

Reads `teleclaude.yml`, ensures `project_slug` is set (deriving one from
`project_name` or the directory name via `normalize_slug` when missing or
invalid), and writes it back in place using comment-preserving YAML. Then
appends the absolute project root to `~/.teleclaude/projects.yaml`
idempotently.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

`telec projects init` is the **sole** writer of the project registry. `telec sync`
must not mutate `~/.teleclaude/projects.yaml`. Once registered, the project
is visible to `ProjectCatalogService` and every consumer that iterates
projects (docs cross-project namespace, job orchestration, etc.).
<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

`telec projects init` owns general project enrollment and is the only path that
persists a missing or repaired `project_slug`. Bare `telec sync` never mutates
`~/.teleclaude/projects.yaml`; an explicit deployment may idempotently register a
root that declares itself as an artifact publisher. Once registered, the project
is visible to `ProjectCatalogService` and every consumer that iterates projects
(docs cross-project namespace, job orchestration, etc.).
<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

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

- Capability subscriptions declared in `teleclaude.yml` and projected as markers under
  the repository's common git directory.
- Git filters, `.gitattributes`, and code hooks configured for the capabilities the
  project subscribes to — a project subscribing neither `code` nor `docs` receives none
  of them.

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
