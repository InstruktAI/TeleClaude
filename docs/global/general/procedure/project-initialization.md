---
description: 'The project setup pipeline that telec config project create, adopt and init share — repository, placement and owner, capabilities, git plumbing, registration.'
visibility: 'public'
---

# Project Initialization — Procedure

## Goal

Set a project up for TeleClaude. Three commands share this pipeline:

- `telec config project create <name>` makes a new, empty project and runs it.
  The project lands in the caller's own home's `projects/<name>`, in a company's
  `projects/<name>` with `--company <slug>`, or, for a platform administrator,
  at a folder outside every home with `--path <dir>`.
- `telec config project adopt` runs it for the folder the caller stands in,
  registering existing work where it already is.
- `telec config project init` re-runs it for a project already registered, to
  converge it. It creates and adopts nothing.

Machine-global agent infrastructure is installed by the TeleClaude checkout's
`make install`.

Initialization starts no agent session. AI-driven project analysis and quality-config
assessment are separate sessions the operator starts explicitly — see the
project-onboarding procedure (`general/procedure/project-onboarding`).

## Preconditions

- For `create`: the name is a valid slug that no project on this computer holds.
- For `adopt`: the folder holds the project's work.
- For `init`: the folder is a registered project. For any other folder `init`
  refuses and names `create` and `adopt`.
- `telec` CLI is available and the daemon is running.

## Steps

### 0. Check placement and owner

Before any later step writes, the pipeline checks where the project sits. A
project `create` makes inside a home lands directly in that home's `projects/`
folder; `adopt` keeps a project wherever it already is. Inside a home the project
declares that home's owner — `create` and `adopt` record it — and a declaration
naming any other owner, or none, is refused. Outside every home the
project keeps the owner it declares, or none; a project `create` makes there has
none.

### 1. Ensure git repository

Initializes a git repository on the `main` branch when the folder is not already
inside one, or when the repository it is inside is the global home's: the global
home's repository never holds a project. A folder inside any other repository
keeps its repository and branches as they are. `create` always starts a new
repository.

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

A project `create` makes is empty, so it declares no capability block yet. The
first `init` after its content is scaffolded infers them from what was built.

This step runs before any capability-gated step below, so a project receives only the
plumbing it subscribes to. Everything downstream reads the declaration; nothing
re-infers from repository shape at runtime.

Source: `teleclaude/project_setup/init_flow.py:_declare_inferred_capabilities()`
and `teleclaude/project_setup/capability_markers.py:project_capabilities()`

### 2b. Scaffold the local baseline manifests (`docs` only)

For a project subscribing `docs`, creates the local baseline manifests under
`docs/local/` from the platform's documentation template when they are absent.
An existing manifest is never changed: it is the project's own curation.

### 2c. Enable and scaffold the help desk (`--help-desk` only)

With `--help-desk`, and only for a caller with administrator authority over the
project, sets the project's help desk as enabled in `teleclaude.yml` and brings
the project's `help-desk/` folder to the project help-desk template: its master
is the template's rendering after every such run, and no other file in the
folder is replaced. The files land in the working tree for the project to commit.

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
configuration writer's lock files — and that state is never offered for commit.

A root carrying no project declaration is not adopted by this act: it is left
byte-for-byte unchanged, with no hook and no filter written or read for it.

Source: `teleclaude/project_setup/plumbing.py:converge_plumbing()`

### 5. Publish nothing

The pipeline runs no artifact sync and publishes nothing. Snippet indexes,
generated `AGENTS.md` entrypoints, and distributed runtime artifacts reach
readers from committed state at the commit boundary
(`general/procedure/doc-snippet-authoring`).

### 6. Deploy the quality skeleton (`code` only)

Deploys the quality skeleton for a downstream project subscribing `code`. The
TeleClaude checkout deploys none — the skeleton is a downstream-project concern.

Hook installation is not part of this step; it belongs to the convergence act
above, which every trigger shares.

Source: `teleclaude/project_setup/skeleton.py:deploy_skeleton()`

### 7. Ensure `project_slug` and register the project root

Reads `teleclaude.yml`, ensures `project_slug` is set (the name `create` was given,
or for `adopt` one derived from `project_name` or the directory name via
`normalize_slug` when missing or invalid), and writes it back in place using
comment-preserving YAML. `create` and `adopt` then append the project's durable main checkout to `~/.teleclaude/projects.yaml`
idempotently. The registered path is always that canonical checkout: invoked
from a linked worktree, initialization resolves back to the owning checkout, so
an ephemeral worktree path never enters the registry.

Creation and adoption are the only writers of the project registry, whether
`telec config project create`, `telec config project adopt`, or the daemon's
add-project request invokes them; `init` records nothing. A folder whose
identity another registry entry already holds is refused before any step
writes, and a folder declaring the person
or company tier is recorded without these steps. Publication must not mutate
`~/.teleclaude/projects.yaml`. Once registered, the project is visible to
`ProjectCatalogService` and every consumer that iterates projects (resolution of
`local/projects/<slug>/…` documentation identities, job orchestration, etc.).

Source: `teleclaude/project_setup/init_flow.py:_ensure_project_slug()`
and `teleclaude/project_manifest.py:register_root()`

<!-- planned-change:retire-event-domains -->

### 8. Seed event domains

Merges default event domain configurations into the global config
(`~/.teleclaude/teleclaude.yml`) under `event_domains.domains`. Idempotent — skips
if domains already have entries, preserving user customizations.

Only `init` runs this step, and only for a caller whose platform role is
member or administrator. For any other caller `init` converges the project and
skips this step. `create` and `adopt` skip it.

Source: `teleclaude/project_setup/domain_seeds.py:seed_event_domains()`

### 9. Watcher ownership

<!-- change:retire-event-domains -->

### 8. Watcher ownership

<!-- /planned-change:retire-event-domains -->

The pipeline does **not** install watchers. `create` and `adopt` register the
project root in `~/.teleclaude/projects.yaml`. Machine-global setup is installed by `make install`,
and service startup/install is owned by `make start`; the global watcher reads this
manifest to decide which projects to watch and sync surgically.

Source: `teleclaude/project_manifest.py:register_root()`

## Outputs

<!-- planned-change:retire-event-domains -->

- Capability subscriptions declared in `teleclaude.yml` and projected as markers under
  the repository's common git directory.
- Git filters, `.gitattributes`, and code hooks configured for the capabilities the
  project subscribes to — a project subscribing neither `code` nor `docs` receives none
  of them.

- `project_slug` persisted in `teleclaude.yml` and, for `create` and `adopt`, the
  project root registered in `~/.teleclaude/projects.yaml`.
- For a project inside a home, that home's owner declared in `teleclaude.yml`.
- For `init` only, and only for a caller whose platform role is member or administrator: event domains seeded in global config (if not already populated).
- The local baseline manifests, when the project subscribes `docs` and they were absent.
- With `--help-desk`: the help desk enabled in `teleclaude.yml` and the `help-desk/` folder scaffolded.

<!-- change:retire-event-domains -->

- Capability subscriptions declared in `teleclaude.yml` and projected as markers under
  the repository's common git directory.
- Git filters, `.gitattributes`, and code hooks configured for the capabilities the
  project subscribes to — a project subscribing neither `code` nor `docs` receives none
  of them.

- `project_slug` persisted in `teleclaude.yml` and, for `create` and `adopt`, the
  project root registered in `~/.teleclaude/projects.yaml`.
- For a project inside a home, that home's owner declared in `teleclaude.yml`.
- The local baseline manifests, when the project subscribes `docs` and they were absent.
- With `--help-desk`: the help desk enabled in `teleclaude.yml` and the `help-desk/` folder scaffolded.

<!-- /planned-change:retire-event-domains -->

## Recovery

- `telec config project init` is idempotent. Re-running it is safe and will skip already-configured steps.
- A refused `create` names its cause: a taken or invalid name, a path inside a home, or `--path` combined with `--company`. Nothing has been written.

## See Also

- ~/.teleclaude/docs/general/procedure/project-onboarding.md
- ~/.teleclaude/docs/sdlc/procedure/project-analysis.md
- ~/.teleclaude/docs/sdlc/spec/init-scaffolding.md
- ~/.teleclaude/docs/general/procedure/company-onboarding.md
