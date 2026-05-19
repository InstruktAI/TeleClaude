---
id: 'project/spec/feature/workflow/worktree-prep-lifecycle'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Per-slug git worktree branched from origin/main with a digest-tracked prep marker that decides when to re-install dependencies; cleanup archives binaries and removes worktree+branch at delivery.'
---

# Worktree Prep Lifecycle — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

Every Todo that enters Phase B work runs in its own isolated git worktree at `trees/<slug>/`, branched from the latest `origin/main`. The worktree is created on demand the first time the work state machine asks for it, and a JSON prep marker recorded inside the worktree at `.teleclaude/worktree-prep-state.json` tracks the digest of the inputs that affect dependency installation. On every subsequent entry the digest is recomputed and compared against the marker: unchanged digests skip preparation entirely, changed digests (or a missing or corrupt marker) trigger re-prep. Concurrent ensure-and-prep on the same `(project_root, slug)` pair is serialized through an async single-flight lock so two work sessions never race the same worktree. When the Todo is delivered, cleanup archives binary artifact directories out of `workspace/<slug>/` into long-term storage, removes the worktree, deletes the local and remote branches, and clears the workspace symlink — every step idempotent so a re-run on already-cleaned state is a no-op.

## Canonical fields

### Use cases

```
Given no worktree exists at `trees/<slug>/`
When `telec todo work <slug>` triggers `_ensure_worktree_ready`
Then `ensure_worktree_with_policy` runs `git fetch origin main` and `git worktree add trees/<slug> -b <slug> origin/main`
And the prep policy reports `worktree_created` and runs preparation
And after prep succeeds, `.teleclaude/worktree-prep-state.json` is written with the computed inputs digest and `version: 1`
```

```
Given a worktree exists with a valid prep marker matching the current inputs digest
When the work state machine re-enters
Then `_decide_worktree_prep` returns `should_prepare=False` with reason `unchanged_known_good`
And no installer commands run
And the work loop proceeds directly to merge origin/main into the worktree branch
```

```
Given a worktree has a prep marker but a dependency input file changed since prep ran
When `_compute_prep_inputs_digest` returns a digest that differs from the marker
Then `_decide_worktree_prep` returns `should_prepare=True` with reason `prep_inputs_changed`
And `_prepare_worktree` re-runs the resolved installer
And on success the marker is rewritten with the new digest
```

```
Given the prep marker file is missing or its JSON is corrupt
When `_read_worktree_prep_state` returns None
Then `_decide_worktree_prep` returns `should_prepare=True` with reason `prep_state_missing`
And preparation runs as if no marker existed
And the corrupt marker is overwritten on success
```

```
Given two `telec todo work <slug>` invocations target the same project root and slug
When both reach `_ensure_worktree_ready`
Then the per-(canonical_cwd, slug) `asyncio.Lock` from `_SINGLE_FLIGHT_LOCKS` serializes them
And the second invocation logs `single_flight_in_progress` and waits for the first to release
And only one prep execution runs against the worktree
```

```
Given two different project roots happen to share a slug name
When work runs concurrently in each project
Then the single-flight registry keyed on `(canonical_cwd, slug)` keeps them isolated
And both worktrees prep in parallel without contention
```

```
Given a Todo reaches the delivered state and `cleanup_delivered_slug` is invoked
When the worktree at `trees/<slug>/` and workspace directory at `workspace/<slug>/` exist
Then `_archive_binary_artifacts` moves any non-empty `art/`, `html/`, and `input/` subdirectories under `workspace/<slug>/` to `~/.teleclaude/storage/<delivery_date>/<slug>/`
And `git worktree remove --force trees/<slug>` runs
And `git branch -D <slug>` removes the local branch
And `git push origin --delete <slug>` removes the remote branch with a 5-second timeout
And the `workspace/<slug>/` directory or symlink is removed
```

```
Given `cleanup_delivered_slug` is invoked twice for the same slug
When the second call runs
Then every step finds its artifact already gone and is a no-op
And no exception is raised; warnings are logged for failures but never block cleanup
```

```
Given `tools/worktree-prepare.sh` exists and is executable
When `_prepare_worktree` runs
Then the script is invoked from the project root with the slug as its only argument
And a non-zero exit code raises `RuntimeError` containing stdout and stderr
And the work state machine surfaces `WORKTREE_PREP_FAILED` to the caller
```

```
Given no `tools/worktree-prepare.sh` exists
When `_prepare_worktree` falls back through its policy
Then `make install` runs if Makefile defines an `install` target
Otherwise `pnpm install` runs if `pnpm-lock.yaml` exists or pnpm is on PATH
Otherwise `npm install` runs if `package.json` exists
Otherwise prep is a no-op and the marker is still written so subsequent calls skip
```

### Implementation pointers (v1)

- `teleclaude/core/next_machine/worktrees.py:35-37` — `_worktree_prep_state_path` resolves the marker location
- `teleclaude/core/next_machine/worktrees.py:40-62` — `_compute_prep_inputs_digest` hashes root and worktree input files, existence flags, and executable bits
- `teleclaude/core/next_machine/worktrees.py:65-95` — `_read_worktree_prep_state` / `_write_worktree_prep_state` enforce version `1` and `inputs_digest` shape
- `teleclaude/core/next_machine/worktrees.py:98-108` — `_decide_worktree_prep` policy returning `worktree_created`, `prep_state_missing`, `prep_inputs_changed`, or `unchanged_known_good`
- `teleclaude/core/next_machine/worktrees.py:111-158` — `_create_or_attach_worktree` fetches origin/main and runs `git worktree add … -b <slug> origin/main`; attaches existing branch on conflict
- `teleclaude/core/next_machine/worktrees.py:161-174` — `ensure_worktree_with_policy` and its async wrapper compose create + decide + prep into one boundary
- `teleclaude/core/next_machine/worktrees.py:177-272` — `_prepare_worktree` policy chain (`tools/worktree-prepare.sh` → `make install` → `pnpm install` → `npm install`)
- `teleclaude/core/next_machine/_types.py:129-146` — `_PREP_STATE_VERSION = 1`, `_WORKTREE_PREP_STATE_REL`, `_PREP_INPUT_FILES`, `_PREP_ROOT_INPUT_FILES`
- `teleclaude/core/next_machine/work.py:55-69` — `_SINGLE_FLIGHT_LOCKS` registry keyed on `(canonical_cwd, slug)` and `_get_slug_single_flight_lock`
- `teleclaude/core/next_machine/work.py:390-428` — `_ensure_worktree_ready` acquires the slug lock, runs `ensure_worktree_with_policy_async`, surfaces `WORKTREE_PREP_FAILED` on RuntimeError
- `teleclaude/core/next_machine/delivery.py:35-67` — `_BINARY_ARTIFACT_DIRS` (`art`, `html`, `input`) and `_archive_binary_artifacts` move into `STORAGE_DIR/<delivery_date>/<slug>/`
- `teleclaude/core/next_machine/delivery.py:70-106` — `cleanup_delivered_slug` runs archive, worktree remove, local branch delete, remote branch delete (timeout 5s), workspace removal
- `teleclaude/constants.py:388` — `WORKTREE_DIR = "trees"`
- `teleclaude/paths.py:32` — `STORAGE_DIR = ~/.teleclaude/storage`

### Cross-context references

- `git` (system tool, not a bounded context) — worktree add/remove, branch create/delete, fetch, push --delete; all wrappers route through `teleclaude.git.Repo`
- filesystem — prep marker at `<worktree>/.teleclaude/worktree-prep-state.json`; archive root at `~/.teleclaude/storage/<delivery_date>/<slug>/`; workspace symlink at `<project_root>/workspace/<slug>/`
- `workflow` — delivery cleanup is invoked from the integration state machine's CLEANUP phase and from any code path that observes `roadmap.status = 'delivered'` (e.g., `_sweep_stale_artifacts`)

## Known caveats

- Prep marker version is currently `1`. A future schema bump must reject older marker files in `_read_worktree_prep_state` and force re-prep with reason `prep_state_missing`.
- The worktree branch is created from `origin/main`, not local main. Any artifact a worker expects to see in the worktree (todo scaffolding, prior commits) must already be reachable on origin/main before the worktree is created; otherwise the branch is missing it until a manual merge.
- The peer convention is `trees/<slug>` for per-todo worktrees and `trees/_integration/` for the integration worktree. The `_sweep_stale_artifacts` scanner and the FIFO candidate scanner both skip subdirectories whose names start with `_`.
- `_compute_prep_inputs_digest` hashes input file *existence*, *executable bit*, and *contents* — so adding a previously absent dependency manifest (e.g., introducing `pyproject.toml`) triggers re-prep on the next entry even if the worktree itself is unchanged.
- The fallback installer policy in `_prepare_worktree` is intentional: when `tools/worktree-prepare.sh` is absent, the script-less path tries `make install`, then pnpm, then npm. A repo with none of these gets a silent no-op prep — and the marker is still written, so the policy never re-runs unless inputs change.
- Cleanup uses a 5-second timeout for `git push origin --delete <branch>` because the remote operation can hang on flaky networks; failure here is logged as a warning but does not block worktree removal.
- The single-flight lock is asyncio-scoped to one process. Two separate Python processes that both call `ensure_worktree_with_policy` for the same `(cwd, slug)` will both attempt to acquire — race protection at the filesystem level relies on `git worktree add` failing fast on the second attempt and the prep marker being overwritten only on success.
- Workspace cleanup removes either a symlink or a directory at `workspace/<slug>/`; this matches the convention used by image and HTML generation flows that maintain `workspace/<slug>/` as a stable path for non-code artifacts during work.
