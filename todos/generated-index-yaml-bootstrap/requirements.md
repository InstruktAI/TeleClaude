# Requirements: generated-index-yaml-bootstrap

## Goal

Transition `index.yaml` files from version-controlled source to locally generated
build artifacts, so they are never committed but always reliably produced by the
toolchain.

## Scope

### In scope

- Preventing git from tracking any `index.yaml` file in the repository.
- Ensuring bootstrap and init flows produce all required `index.yaml` files
  before any step that depends on them.
- Replacing git-HEAD-based recovery of `index.yaml` with regeneration.
- Removing stale git filter configuration that applies only to tracked
  `index.yaml` files.
- Cleaning up symlink deployment logic that references `index.yaml` as a
  tracked file.
- Verifying watcher behavior treats `index.yaml` as a generated artifact.
- Targeted test coverage for the changed behaviors.

### Out of scope

- Changing how `telec sync` generates `index.yaml` content or schema.
- Changing the `baseline.md` handling in sync repair (remains tracked).
- Modifying snippet taxonomy structure or context selector logic.

## Requirements

### R1 — Git exclusion

`index.yaml` files must not be tracked by git anywhere in the repository.
Currently tracked instances must be removed from the index while preserving
them as local files for immediate use.

**Success criteria:**

- `git ls-files '**/index.yaml'` returns no results after the change.
- Git ignore rules prevent future accidental commits of `index.yaml` files.

### R2 — Bootstrap generation ordering

A fresh `telec init` must produce all required `index.yaml` files before any
step that reads or distributes them. The generation must succeed on a clean
checkout where no `index.yaml` files exist on disk.

**Success criteria:**

- `telec init` on a fresh clone produces `index.yaml` files at all snippet
  root locations before watcher installation or artifact distribution.
- No step in the init flow fails due to a missing `index.yaml`.

### R3 — Recovery by regeneration

Sync recovery logic must not attempt to restore `index.yaml` from git HEAD.
When an `index.yaml` file is missing or corrupt, the recovery path is
regeneration via the existing index builder — not git object retrieval.

**Success criteria:**

- The sync pipeline does not invoke git commands to recover `index.yaml`
  content.
- A missing `index.yaml` is recovered by the normal index build step, not
  by a separate repair mechanism.

### R4 — Watcher stability

The filesystem watcher must continue treating `index.yaml` as a generated
sync output that does not trigger re-runs. `[inferred]` The current watcher
behavior already satisfies this — this requirement exists to verify no
regression is introduced by the other changes.

**Success criteria:**

- Changes to `index.yaml` do not trigger a watcher sync cycle.
- The watcher operates correctly when `index.yaml` is absent at startup
  (fresh clone scenario).

### R5 — Distribution pipeline compatibility

The artifact distribution step that symlinks global docs to the user's home
directory must continue to work when `index.yaml` is an untracked local file
rather than a git-tracked file.

**Success criteria:**

- `~/.teleclaude/docs/index.yaml` resolves to a valid index after `telec sync`
  runs.
- The distribution step does not depend on `index.yaml` being tracked by git.

### R6 — Git filter cleanup `[inferred]`

The `.gitattributes` filter rule for `docs/*/index.yaml` becomes inert when
`index.yaml` is untracked. It should be removed to prevent confusion about
what the filter applies to.

**Success criteria:**

- No git filter rules reference `index.yaml` patterns.

### R7 — Process documentation alignment `[inferred]`

Any documentation or inline comments that describe `index.yaml` as a tracked
or authored file must be updated to reflect its generated-artifact status.
This includes doc snippets that reference the git docs filter applying to
`index.yaml`.

**Success criteria:**

- No documentation describes `index.yaml` as tracked, authored, or manually
  maintained.

### R8 — Test coverage

Targeted tests must cover the changed behaviors: bootstrap generation on a
clean state, sync recovery without git fallback, and watcher exclusion of
generated index files.

**Success criteria:**

- Tests verify that the sync pipeline produces `index.yaml` files without
  relying on git HEAD content.
- Tests verify that the watcher excludes `index.yaml` from triggering syncs.
- Tests verify bootstrap ordering — index generation precedes distribution.

## Constraints

- The change must be backward-compatible: existing local environments with
  tracked `index.yaml` files must continue to work after pulling the change
  (git rm --cached preserves the local copy).
- `telec sync` generation logic and `index.yaml` content schema are unchanged.
- `baseline.md` repair logic in sync is unaffected.

## Risks

- **Stale local index after branch switch:** switching to an older branch that
  still tracks `index.yaml` and then back to main could leave the local file
  in a state that was not regenerated. Mitigation: the watcher and `telec sync`
  already regenerate on relevant source changes.
- **CI environments:** CI pipelines that depend on `index.yaml` existing in the
  checkout must run `telec sync` first. `[inferred]` This is already the case
  since CI runs hooks that include sync.
