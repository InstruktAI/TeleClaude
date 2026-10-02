---
description: 'Complete telec config project init pipeline — project git plumbing, artifact sync, event domain seeding, project registration.'
visibility: 'public'
---

# Project Initialization — Procedure

## Goal

Bootstrap a project for TeleClaude by configuring project git plumbing, syncing
artifacts, seeding event domains, and registering the project root. Machine-global
agent infrastructure is installed by the TeleClaude checkout's `make install`.

Initialization starts no agent session. AI-driven project analysis and quality-config
assessment are separate sessions the operator starts explicitly — see the
project-onboarding procedure (`general/procedure/project-onboarding`).

## Preconditions

- The project directory exists and contains source files (or is being initialized).
- `telec` CLI is available and the daemon is running.

## Steps

### 1. Ensure git repository

Initializes a git repository on the `main` branch when the folder is not already
inside one. A folder that is already inside a repository keeps its repository and
branches as they are.

Source: `teleclaude/project_setup/git_repo.py:ensure_git_repo()`

### 2. Declare the project's capability subscriptions

Establishes the project config marker, then infers any capability block the manifest
does not already declare from durable repository structure: a `Makefile` or a
recognized language tree implies `code`, authored snippet frontmatter under `docs/`
implies `docs`, and authored files under `agents/` imply `agents` — `.agents/` is a
delivery location and never an inference source. Only missing
blocks are materialized — an explicit declaration is preserved, never overwritten.
The resolved subscriptions are then projected as markers under the repository's
common git directory, where the installed shell plumbing reads them by existence
check.

This step runs before any capability-gated step below, so a project receives only the
plumbing it subscribes to. Everything downstream reads the declaration; nothing
re-infers from repository shape at runtime.

Source: `teleclaude/project_setup/init_flow.py:_declare_inferred_capabilities()`
and `teleclaude/project_setup/capability_markers.py:project_capabilities()`

### 2b. Scaffold the local baseline manifests (`docs` only)

For a project subscribing `docs`, creates the local baseline manifests under
`docs/local/` from the platform's documentation template when they are absent.
An existing manifest is never changed: it is the project's own curation
(`projects/teleclaude/spec/feature/reconciliation/template-installation`).

### 2c. Enable and scaffold the help desk (`--help-desk` only)

With `--help-desk`, and only for a caller with administrator authority over the
project, sets the project's help desk as enabled in `teleclaude.yml` and brings
the project's `help-desk/` folder to the project help-desk template: its master
is the template's rendering after every such run, and no other file in the
folder is replaced. The files land in the working tree for the project to commit
(`projects/teleclaude/spec/feature/config/kind-addressed-configuration`).

### 3. Update .gitattributes (`docs` only)

Adds filter patterns so that `docs/**/*.md` and `agents/docs/**/*.md` use the
`teleclaude-docs` filter. Idempotent — skips patterns already present. This is the
one project-tracked file TeleClaude writes, and it is written additively at adoption
only; no later capability change edits it.

Source: `teleclaude/project_setup/gitattributes.py:update_gitattributes()`

### 4. Converge the project's git plumbing

Converges the installed plumbing to the declaration in one act, and the same act
serves every other trigger that converges a root.

The docs filter driver is installed for a project subscribing `docs`, and
TeleClaude's driver is removed from the git config of a project that does not, so
the step runs regardless of the declaration's value. The driver handles tilde
expansion — smudge expands the portable `@~/.teleclaude` reference to the absolute
home path on checkout, and clean contracts it back on commit.

Tracked files a checkout left unexpanded, and files still carrying a prior filter
pattern's residue, are re-checked out so the smudge filter applies to them; a locally
modified file is left untouched.

The TeleClaude-owned hook set is then installed for a project whose enabled
capabilities or declared bindings resolve an executable action, from the canonical
sources under `templates/quality/githooks/`. The hooks are language-neutral, so every
such project receives the same set. A hook that already matches its template is left
untouched, and a hook the project authored itself is preserved. A project whose
declaration resolves no executable action receives no TeleClaude-owned hook.

Whatever the project subscribes, the repository's local exclude list names
TeleClaude's machine-local state — the project's `.teleclaude/` directory and the
configuration writer's lock files — and that state is never offered for commit
(`projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`).

A root carrying no project declaration is not adopted by this act: it is left
byte-for-byte unchanged, with no hook and no filter written or read for it.

Source: `teleclaude/project_setup/plumbing.py:converge_plumbing()`

### 5. Sync project artifacts

Runs the bootstrap sync — validation runs and reports findings without blocking — to build
snippet indexes, inflate `AGENTS.master.md` into `AGENTS.md`, and distribute artifacts to
agent runtimes.

This step happens before slug persistence because `sync_project_artifacts()`
materializes a bare `teleclaude.yml` for fresh projects. `telec config project init` then
rewrites that file in place to guarantee `project_slug` exists before the
project is registered.

Source: `teleclaude/project_setup/sync.py:sync_project_artifacts()`

### 6. Deploy the quality skeleton (`code` only)

Deploys the quality skeleton for a downstream project subscribing `code`. The
TeleClaude checkout deploys none — the skeleton is a downstream-project concern.

Hook installation is not part of this step; it belongs to the convergence act
above, which every trigger shares.

Source: `teleclaude/project_setup/skeleton.py:deploy_skeleton()`

### 7. Ensure `project_slug` and register the project root

Reads `teleclaude.yml`, ensures `project_slug` is set (deriving one from
`project_name` or the directory name via `normalize_slug` when missing or
invalid), and writes it back in place using comment-preserving YAML. Then
appends the project's durable main checkout to `~/.teleclaude/projects.yaml`
idempotently. The registered path is always that canonical checkout: invoked
from a linked worktree, initialization resolves back to the owning checkout, so
an ephemeral worktree path never enters the registry.

Adoption is the only writer of the project registry, and this procedure is how
a project is adopted, whether `telec config project init` or the daemon's
add-project request invokes it. A folder whose identity another registry entry
already holds is refused before any step writes, and a folder declaring the person
or company tier is recorded without these steps
(`projects/teleclaude/spec/feature/config/project-registry`). Publication must not mutate
`~/.teleclaude/projects.yaml`. Once registered, the project is visible to
`ProjectCatalogService` and every consumer that iterates projects (resolution of
`projects/<slug>/…` documentation identities, job orchestration, etc.).

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

`telec config project init` does **not** install watchers. It registers the project root in
`~/.teleclaude/projects.yaml`. Machine-global setup is installed by `make install`,
and service startup/install is owned by `make start`; the global watcher reads this
manifest to decide which projects to watch and sync surgically.

Source: `teleclaude/project_manifest.py:register_root()`

## Outputs

- Capability subscriptions declared in `teleclaude.yml` and projected as markers under
  the repository's common git directory.
- Git filters, `.gitattributes`, and code hooks configured for the capabilities the
  project subscribes to — a project subscribing neither `code` nor `docs` receives none
  of them.

- `project_slug` persisted in `teleclaude.yml` and project root registered in `~/.teleclaude/projects.yaml`.
- Artifacts synced and indexes built.
- Event domains seeded in global config (if not already populated).
- The local baseline manifests, when the project subscribes `docs` and they were absent.
- With `--help-desk`: the help desk enabled in `teleclaude.yml` and the `help-desk/` folder scaffolded.

## Recovery

- `telec config project init` is idempotent. Re-running it is safe and will skip already-configured steps.
- The bootstrap sync reports validation findings without blocking, so init always completes even when a project already carries findings; the commit gate validates once real work begins.

## See Also

- ~/.teleclaude/docs/general/procedure/project-onboarding.md
- ~/.teleclaude/docs/sdlc/procedure/project-analysis.md
- ~/.teleclaude/docs/sdlc/spec/init-scaffolding.md
- ~/.teleclaude/docs/general/procedure/company-onboarding.md
