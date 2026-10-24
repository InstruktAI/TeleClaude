---
description: 'Per-slug git worktree branched from origin/main with a digest-tracked prep marker that decides when to re-install dependencies; cleanup archives binaries and removes worktree+branch at delivery.'
visibility: 'public'
---

# Worktree Prep Lifecycle — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

Every Todo that enters Phase B work runs in its own isolated git worktree at `trees/<slug>/`. The worktree is created on demand whenever the work state machine asks for it and none exists: a Todo whose build has not started is branched from the latest `origin/main` and its branch opens with an empty commit of its own. Every later commit of the Todo descends from that opening commit, so the commit recorded when its build starts belongs to this Todo alone. A branch carrying the Todo's name that an earlier Todo left behind — when its delivery or removal cleanup did not complete — is never adopted and never discarded while it holds work: on `origin` it stays untouched, and locally it stops the ensure until an agent resolves it; a local leftover holding no work gives way to the new branch. A Todo whose build has started resumes from its branch on `origin` when that branch contains its build-start commit and the commit is not on `origin/main`, so work continues from its last published commit on whichever computer holds the Todo. A Todo whose build-start commit is on `origin/main` and that has no branch under its name, locally or on `origin`, has no work to resume: it starts over like a Todo whose build has not started, and the ensure logs a warning. A build-start commit off `origin/main` with no branch to hold it keeps refusing. A JSON prep marker recorded inside the worktree at `.teleclaude/worktree-prep-state.json` tracks the digest of the inputs that affect dependency installation. On every subsequent entry the digest is recomputed and compared against the marker: unchanged digests skip preparation entirely, changed digests (or a missing or corrupt marker) trigger re-prep. Concurrent ensure-and-prep on the same `(project_root, slug)` pair is serialized through a single-flight lock so two work sessions never race the same worktree. When the Todo is delivered, cleanup archives binary artifact directories out of `workspace/<slug>/` into long-term storage, removes the worktree, deletes the local and remote branches, and clears the workspace symlink — every step idempotent so a re-run on already-cleaned state is a no-op.

<!-- planned:github-pr-collaboration -->

Starting a Todo's build publishes its branch, from the opening commit on, to
`origin` before the build is recorded as started, so the branch exists where
others can follow it from the first moment of the build. A publication that
fails does not stop the build: it is logged, and the branch reaches `origin`
with the Todo's next published commit. What a GitHub-backed project shows for
the branch from then on is owned by
`local/projects/teleclaude/design/architecture/workflow-store`.

<!-- /planned:github-pr-collaboration -->

## Canonical fields

### Use cases

```
Given no worktree exists at "trees/<slug>/"
And the Todo's build has not started
When the work state machine asks the workflow service to ensure the worktree is ready
Then the workflow service fetches origin main and creates the worktree branched from origin/main
And the prep policy reports "worktree_created" and runs preparation
And after prep succeeds, the prep marker is written with the computed inputs digest
```

```
Given a worktree exists with a valid prep marker matching the current inputs digest
When the work state machine re-enters
Then the prep decision returns "unchanged_known_good" with no preparation required
And no installer commands run
And the work loop proceeds directly to merge origin/main into the worktree branch
```

```
Given a worktree has a prep marker but a dependency input file changed since prep ran
When the computed inputs digest differs from the marker
Then the prep decision is "prep_inputs_changed" and preparation is required
And the resolved installer re-runs
And on success the marker is rewritten with the new digest
```

```
Given the prep marker file is missing or its JSON is corrupt
When the workflow service tries to read the marker
Then the prep decision is "prep_state_missing" and preparation is required
And preparation runs as if no marker existed
And the corrupt marker is overwritten on success
```

```
Given two concurrent work calls target the same project root and slug
When both reach the ensure-worktree-ready boundary
Then the single-flight lock for that (project_root, slug) pair serializes them
And the second invocation waits for the first to release
And only one prep execution runs against the worktree
```

```
Given two different project roots happen to share a slug name
When work runs concurrently in each project
Then the single-flight registry keyed on (project_root, slug) keeps them isolated
And both worktrees prep in parallel without contention
```

```
Given a Todo reaches the delivered state and delivered-slug cleanup is invoked
When the worktree at "trees/<slug>/" and workspace directory at "workspace/<slug>/" exist
Then any non-empty "art/", "html/", and "input/" subdirectories under "workspace/<slug>/" are archived to long-term storage under the delivery date
And the worktree is detached from its active location without waiting for bulk disk reclamation
And the local branch is removed
And the remote branch is removed with a short timeout
And the "workspace/<slug>/" directory or symlink is removed
```

```
Given delivered-slug cleanup is invoked twice for the same slug
When the second call runs
Then every step finds its artifact already gone and is a no-op
And no exception is raised; warnings are logged for failures but never block cleanup
```

```
Given "tools/worktree-prepare.sh" exists and is executable
When preparation runs
Then the script is invoked from the project root with the slug as its only argument
And a non-zero exit code raises a preparation failure containing stdout and stderr
And the work state machine surfaces WORKTREE_PREP_FAILED to the caller
```

```
Given no "tools/worktree-prepare.sh" exists
When preparation falls back through its policy
Then it runs "make install" if a Makefile defines an "install" target
Otherwise "pnpm install" if a pnpm lockfile exists or pnpm is on PATH
Otherwise "npm install" if a "package.json" exists
Otherwise prep is a no-op and the marker is still written so subsequent calls skip
```

#### UC-WPL1: An ensured worktree resolves its configuration schemas

```
Given a slug worktree of an adopted project, whether newly created or already prepared
When the work state machine asks the workflow service to ensure the worktree is ready
Then the worktree carries its own configuration-schema link to the TeleClaude home's published schemas
And that holds whether or not preparation ran
And the link does not appear among the worktree's untracked files
And no worktree-tracked file is edited
```

#### UC-WPL2: A started Todo with no worktree resumes from its own published branch

```
Given a computer holds a Todo whose build has started
And no worktree exists for it at "trees/<slug>/" and no local branch carries its name
And the Todo's branch on origin contains the commit recorded when the Todo's build started
And that commit is not on origin/main
When the work state machine asks the workflow service to ensure the worktree is ready
Then the worktree is created on a local branch that starts at the Todo's branch on origin
And the work continues from the last commit published on that branch
And the prep policy reports "worktree_created" and runs preparation
```

#### UC-WPL3: A local branch behind the Todo's published branch is brought up to it

```
Given a Todo whose build has started has no worktree at "trees/<slug>/"
And a local branch carries the Todo's name
And the Todo's branch on origin contains the commit recorded when the Todo's build started and every commit on the local branch
And the build-start commit is not on origin/main
When the work state machine asks the workflow service to ensure the worktree is ready
Then the local branch is advanced to the Todo's branch on origin
And the worktree is created on it
```

#### UC-WPL4: A local branch that diverged from the Todo's published branch stops the ensure

```
Given a Todo whose build has started has no worktree at "trees/<slug>/"
And a local branch carries the Todo's name
And the local branch and the Todo's branch on origin each hold commits the other does not
When the work state machine asks the workflow service to ensure the worktree is ready
Then no worktree is created and neither branch changes
And the work state machine reports a worktree setup failure naming both branch tips
```

#### UC-WPL5: A same-named local branch holding work stops a Todo's first worktree

```
Given a Todo whose build has not started has no worktree at "trees/<slug>/"
And a local branch carries the Todo's name and changes files relative to origin/main
When the work state machine asks the workflow service to ensure the worktree is ready
Then no worktree is created and the local branch is unchanged
And the work state machine reports a worktree setup failure naming the branch and its tip
```

#### UC-WPL8: A Todo's first worktree opens its branch with a commit of its own

```
Given a Todo whose build has not started has no worktree at "trees/<slug>/"
When the work state machine asks the workflow service to ensure the worktree is ready
Then the worktree's branch starts with an empty commit that is neither on origin/main nor on any other Todo's branch
And the commit recorded when the Todo's build starts descends from it
```

#### UC-WPL9: A started Todo whose build-start commit is on origin/main never adopts a remote branch

```
Given a Todo whose build has started has no worktree at "trees/<slug>/"
And the commit recorded when the Todo's build started is on origin/main
When the work state machine asks the workflow service to ensure the worktree is ready
Then no branch on origin is adopted as the Todo's work
And a local branch carrying the Todo's name is attached when one exists
And otherwise, when origin holds a branch under the Todo's name, no worktree is created and the work state machine reports that the Todo's work cannot be located
```

#### UC-WPL7: A same-named local branch holding no work gives way to the Todo's own branch

```
Given a Todo whose build has not started has no worktree at "trees/<slug>/"
And a local branch carries the Todo's name and changes no file relative to origin/main
When the work state machine asks the workflow service to ensure the worktree is ready
Then the worktree is branched from origin/main under the Todo's name
And the branch opens with the Todo's own commit and carries none of the earlier branch's commits
```

#### UC-WPL10: A same-named branch on origin is neither adopted nor removed by a Todo's first worktree

```
Given a Todo whose build has not started has no worktree at "trees/<slug>/"
And origin holds a branch under the Todo's name
When the work state machine asks the workflow service to ensure the worktree is ready
Then the worktree is branched from origin/main
And the branch on origin is unchanged
```

#### UC-WPL6: A started Todo whose work is on no branch stops the ensure

```
Given a Todo whose build has started has no worktree at "trees/<slug>/" and no local branch carries its name
And no branch on origin under the Todo's name contains the commit recorded when the Todo's build started, or that commit is on origin/main
And that commit is not on origin/main, or origin holds a branch under the Todo's name
When the work state machine asks the workflow service to ensure the worktree is ready
Then no worktree is created
And the work state machine reports a worktree setup failure stating that the Todo's work is not on origin
```

#### UC-WPL12: A started Todo whose build-start commit is on origin/main and has no branch anywhere starts over

```
Given a Todo whose build has started has no worktree at "trees/<slug>/"
And the commit recorded when the Todo's build started is on origin/main
And no branch carries the Todo's name, locally or on origin
When the work state machine asks the workflow service to ensure the worktree is ready
Then the worktree is branched from origin/main and opens with the Todo's own commit
And the prep policy reports "worktree_created" and runs preparation
```

#### UC-WPL11: Reclamation preserves a worktree that reuses a released slug

```gherkin
Given a released worktree awaits background disk reclamation
And a human operator starts another Todo that reuses the released slug
When background maintenance reclaims the detached worktree
Then the newly active worktree remains intact
And reclamation runs off the daemon's event loop
```

### Cross-context references

- `git` (system tool, not a bounded context) — worktree add/remove, branch create/delete, fetch, push --delete.
- filesystem — prep marker at `<worktree>/.teleclaude/worktree-prep-state.json`; archive root under the long-term storage directory; workspace symlink at `<project_root>/workspace/<slug>/`.
- `workflow` — delivery cleanup is invoked from the integration state machine's cleanup phase and from any code path that observes a delivered status.
- `reconciliation` — owns the configuration-schema link; ensuring a worktree invokes its published link operation for the worktree root (`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`).
- `agent_runtime` — owns agent runtimes' workspace trust for slug worktrees; ensuring a worktree, renaming its todo, and delivered-slug cleanup invoke its published add, move, and remove operations for the worktree path, and none of them fails the worktree step (`local/projects/teleclaude/spec/feature/agent_runtime/worktree-workspace-trust`).

<!-- planned:release-development-checkouts -->

### Associated development ownership

For an installation/development pair, source worktrees and their environment
belong to the registered development checkout, while workflow records use the
logical project's one state root. Root-relative paths in this spec refer to that
worktree owner, as resolved by
`local/projects/teleclaude/design/architecture/command-scope`. A shared environment
within the development tree never aliases the installed runtime environment.
Existing worktree claims and unpublished work are preserved during association
migration under `sdlc/policy/version-control-safety`.
<!-- /planned:release-development-checkouts -->

<!-- planned:reviewed-pr-contributions -->

### Contribution materialization

Contribution intake first materializes the pinned proposal as source without
running execution-capable preparation. After the upstream reviewer permits
normal validation, the existing preparation contract applies to the adopted
worktree (`local/projects/teleclaude/spec/feature/workflow/contribution-adoption`).
Contributor worktrees keep their upstream baseline separate from the remote
that stores their writable proposal branches
(`local/projects/teleclaude/spec/feature/workflow/contribution-export`). Resume
and retirement operate on those recorded branch identities, not on a guessed
single remote.
<!-- /planned:reviewed-pr-contributions -->

## Known caveats

- Cleanup releases the active worktree path by moving it into a unique project-local trash entry on the same filesystem. The existing daemon maintenance pass reclaims detached entries at startup and periodically; it keeps the trash container available for concurrent detachment, and a failed deletion is logged and retried on a later pass. Isolated-home deletion, workspace cleanup, and branch operations remain part of the caller-awaited cleanup.

- A worktree owns no Python environment of its own. Preparation creates `.venv` as a symlink to the project root's, clearing anything already at that path first (`tools/worktree-prepare.sh`), and symlinks `.env` from the root the same way; only `config.yml` is generated per worktree, giving it an isolated database. So dependencies resolve to the root environment, and installing from a worktree installs into the root's.
- A worktree-local `.venv` is a symlink to a directory, which means `test -d` and a bare `ls` of the path both report it as an ordinary directory. `ls -l` on the worktree, `ls -ld`, or `readlink` show what it is. An existence probe answers whether something is there, never what it is — read this section rather than inferring the shape from a probe.
- A future prep marker schema bump must reject older marker files and force re-prep with reason `prep_state_missing`.
- A new worktree branch is created from the Todo's own branch on `origin` when its build has started, otherwise from `origin/main` — never from local main. A branch on `origin` counts as the Todo's own only when it contains the commit recorded at the Todo's build start and that commit is not on `origin/main`: only then is the commit unique to the Todo, through the opening commit its first worktree made. A build-start commit that is on `origin/main` is shared with every branch cut from it — including a same-named branch an earlier Todo left on `origin` — so such a Todo never adopts a remote branch. Any artifact a worker expects to see in the worktree (todo scaffolding, prior commits) must already be reachable on one of those before the worktree is created; otherwise the branch is missing it until a manual merge. Commits that exist only on another computer's local branch are invisible here.

- The peer convention is `trees/<slug>` for per-todo worktrees and `trees/_integration/` for the integration worktree. Scanners skip subdirectories whose names start with `_`.
- The inputs digest hashes input file _existence_, _executable bit_, and _contents_ — so adding a previously absent dependency manifest (e.g., introducing `pyproject.toml`) triggers re-prep on the next entry even if the worktree itself is unchanged.
- The fallback installer policy is intentional: when `tools/worktree-prepare.sh` is absent, the script-less path tries `make install`, then pnpm, then npm. A repo with none of these gets a silent no-op prep — and the marker is still written, so the policy never re-runs unless inputs change.
- Cleanup uses a short timeout for the remote branch delete because the remote operation can hang on flaky networks; failure here is logged as a warning but does not block worktree removal.
- The single-flight lock is scoped to one process. Two separate processes that both ask to ensure the same `(project_root, slug)` worktree will both attempt to acquire — race protection at the filesystem level relies on `git worktree add` failing fast on the second attempt and the prep marker being overwritten only on success.
- Workspace cleanup removes either a symlink or a directory at `workspace/<slug>/`; this matches the convention used by image and HTML generation flows that maintain `workspace/<slug>/` as a stable path for non-code artifacts during work.
