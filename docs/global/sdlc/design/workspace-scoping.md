---
description: "How telec code commands resolve workspace scope from session declarations and compose the project's native make targets with the TeleClaude guardrails lane across isolated worktrees, shared branches, and explicit file overrides."
visibility: 'public'
---

# Workspace Scoping — Design

## Purpose

`telec code` commands run from isolated worktrees, shared branches, human shells,
and CI. Workspace scoping decides which paths belong to the current operation
without stashing and without touching another agent's in-progress files.

`telec code` is the scoping and composition layer. It resolves which files the
current operation owns, then delegates execution — it embeds no toolchain of its
own. `telec code lint` composes **two decoupled legs**:

1. the project's own `make lint` — native tools (ruff/pyright/mypy/jscpd, eslint/tsc,
   cargo) with **zero TeleClaude dependency**; and
2. TeleClaude's **guardrails lane** — the policy checks
   (`tools/lint/{guardrails,markdown,home_paths,snapshot_testing}.py`
   plus the doc-index resource-validation).

`make lint` never contains the guardrails lane and never calls `telec`; the
guardrails lane is never plumbed into any `Makefile`. The native Makefile shape
is identical for TeleClaude's own repo and any adopting project, while the
current guardrails lane remains TeleClaude-repo-rooted.
`telec code test|format|install` are pure delegations to
`make test|format|install`.

Three execution contexts drive file resolution:

1. **Worktree** — isolated by design. All dirty paths in the worktree belong to
   the task.
2. **Shared branch with session identity** — multiple agents may have
   uncommitted work. Scope to the current session's declared dirty files.
3. **Shared branch without session identity** — human or CI context. Both legs
   run the full suite (no file list).
4. **Explicit files** — caller passes file arguments directly. Skip workspace
   scoping.

`make lint` and `make test` are the project's own entrypoints; they run native
tools directly and do NOT call back into `telec code`. The delegation is
one-directional: `telec code lint` resolves scope and invokes `make lint`,
passing the scoped file list as a **NUL-delimited `FILES_FROM` temp file** (the
paths never travel on `make`'s command line, in `$@`/`$*`, or as a make goal),
and runs the guardrails lane over the same scoped paths. A `make lint` with no
`FILES_FROM` runs the whole suite. There is no `telec code → make → telec code`
cycle.

`telec code commit` runs format then lint in-process against `quality_paths`
(the declared set filtered to existing files) before `git commit --no-verify`.
No framework stash, no working-tree reset outside the declared set. The installed
`.git/hooks/pre-commit` is a thin telec-owned guard performing only a
partial-staging check as a backstop for raw `git commit` invocations.

Tool invocation is separate from file scoping. `telec code` decides which files
are in play; the `make` recipes own how the native tools run, and the guardrails
lane runs the policy scripts (as subprocess argv — argv-safe). In uv-managed
Python projects the make recipes invoke project tools through the uv-managed
entrypoints defined by the Python tooling policy.

The code owner for workspace-derived scope is
`teleclaude/quality/scope.py::resolve_workspace_scope_resolution()`. Callers may
own explicit file arguments, output rendering, staging, or fallback behavior,
but they do not branch on git worktree state directly. Each `telec code` verb
then renders the resolved scope into a `make` invocation (and, for lint, the
guardrails lane).

## Inputs/Outputs

| Input                | Source                                                                                                                                   |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Execution context    | `resolve_workspace_scope_resolution()`                                                                                                   |
| Session identity     | `$TMPDIR/teleclaude_identity.json`                                                                                                       |
| Session declarations | The session's own declaration record, written by `telec code add`                                                                        |
| Dirty paths          | `git status --porcelain --untracked-files=all`                                                                                           |
| Project languages    | Detected from repo artifacts (`pyproject.toml`, `setup.py`, root Python files, `tsconfig.json`, TypeScript `package.json`, `Cargo.toml`) |
| Explicit file list   | CLI arguments (`telec code lint <files...>`)                                                                                             |

| Output                  | Description                                                                                                |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- |
| `dirty_paths`           | Full dirty set from one porcelain parse, including operation kind                                          |
| `scoped_dirty_paths`    | Workspace-owned dirty paths, including deletions, safe for commit staging                                  |
| `scoped_existing_paths` | Workspace-owned existing paths — serialized into `FILES_FROM` (make leg) and passed to the guardrails lane |

### Session path declarations

On a shared branch, session-owned path evidence is exactly the set of paths the
session declared. A declaration is an entry a successful `telec code add` writes
to the declaring session's own record, carrying the path and the instant it was
declared. `add` accepts paths that are clean or do not yet exist: declaring is
bookkeeping and carries no git state of its own. The record is written by the
command itself, so the shell form that carried the invocation, the agent runtime
that ran it, and the readability of the session's transcript are all outside the
evidence path. A declaration is live from the moment it is written until the
commit that carries it lands and clears it; `--only` clears just the subset that
commit carried. Nothing else — file-edit records, shell-command text, or
transcript inspection of any kind — supplies path evidence.

The record is session-scoped durable state, keyed by the declaring session and
released when that session closes. It outlives the agent process, the host pane,
and the machine, so a declaration stays live across an agent restart, a handoff,
and a revival of the same session.

<!-- planned-change:fix-stop-checkpoint-repeats-a-commit-instruc -->
Every implicit-scope consumer on a shared branch reads this same evidence.
Session-scoped lint, commit, and the agent-stop checkpoint each intersect it
with the current dirty set. Worktrees remain task-scoped and do not consult
session declarations: there the same consumers read the dirty set directly,
because a todo checkout has one writer and nothing to attribute.
<!-- change:fix-stop-checkpoint-repeats-a-commit-instruc -->
Every implicit-scope consumer on a shared branch reads this same evidence.
Session-scoped lint, commit, and the agent-stop checkpoint each intersect it
with the current dirty set. A worktree is task-scoped, and its writers are the
sessions whose lifecycle job changes and commits its source: the builder and the
finalizer in a todo worktree, the integrator in the integration worktree. Scoped
lint reads a worktree's dirty set directly for every
session. What a session commits and owes at its agent-stop checkpoint depends on
whether it is a writer: a writer's commit scope is the dirty set, with no
declaration consulted; any other session's commit scope is its own declarations
intersected with the dirty set, as on a shared branch
(`sdlc/procedure/lifecycle/work/review-build`, `sdlc/policy/commits`). The
writer jobs are read from the acting session's record, never from a copy.
<!-- /planned-change:fix-stop-checkpoint-repeats-a-commit-instruc -->

A path is **owned** when it is both declared and dirty. A declared path that is
clean is not owned and appears in no scope. Several sessions may declare the same
path; each is an owner, and no arbitration selects between them.

### Batch dirty-path ownership

The read-only `telec code owners <path>...` query reports which live sessions
have declared a caller-supplied batch of project-relative dirty paths. Its inputs
are the validated paths, one porcelain-derived dirty set, and one snapshot of open
sessions whose project root and computer match the caller. Closed sessions are
outside the snapshot, so a dead session's declarations hold no claim.

The output is one JSON object keyed by every requested path. An owned entry
carries every live declaring session's UUID, job role, and title; a path no live
session declared carries `null`. Declarations are read, never inferred: the query
inspects no transcript for file-edit evidence, consults no commit authorship, and
introduces no durable claim state beyond the declarations themselves.

No lifecycle role depends on this query. It exists as a diagnostic for a human or
agent asking who is working on a path.

## Invariants

1. **No stashing.** The scoping mechanism keeps files outside the agent's scope untouched, so there is never a need to stash anything aside.
<!-- planned-change:fix-stop-checkpoint-repeats-a-commit-instruc -->
2. **Worktrees are task-scoped.** A worktree is isolated — all dirty files
   belong to the task. Existing dirty files drive both legs and the
   commit-staging set; commit staging may also include deleted dirty paths.
<!-- change:fix-stop-checkpoint-repeats-a-commit-instruc -->
2. **Worktrees are task-scoped; their commits belong to their writers.** A
   worktree is isolated — all dirty files belong to the task, and existing
   dirty files drive both lint legs for every session. For a writer session
   the dirty files are also the commit-staging set, which may include deleted
   dirty paths. Any other session stages only its own declared dirty paths.
<!-- /planned-change:fix-stop-checkpoint-repeats-a-commit-instruc -->
3. **Shared branches are declaration-scoped.** On a shared branch, only files the
   current session declared and that are dirty are scoped. This prevents agents
   from linting or committing other agents' in-progress work.
4. **Explicit files override everything.** When the caller passes files as
   arguments, scoping is skipped and those files drive both legs.
5. **Commit gates run in-process, no stash.** `telec code commit` runs format
   then lint against `quality_paths` before `git commit --no-verify`; the thin
   `.git/hooks/pre-commit` performs only a partial-staging backstop. No
   framework stash, no working-tree reset outside the declared set.

6. **Scope failure is an error.** If workspace scope cannot be resolved and no
   explicit files are provided, the command exits non-zero with guidance:
   "pass files explicitly." It never silently falls back to a broader scope.

7. **No session identity on a shared branch means full run.** Human and CI
   contexts have no session identity; both legs run the whole suite.
8. **Tool environment is owned by make and the lane.** Scoping decides what to
   check; the project's `make` recipes own the native tool environment, and the
   guardrails lane owns the policy scripts. `telec code` invokes no tool of its
   own.
9. **`make test` is never file-scoped.** The spec-anchored model has no 1:1
   source→test map, so `telec code test` delegates to `make test` with no scope.
10. **Both legs fail the command.** `telec code lint` runs the native `make lint`
    leg first (ruff `--fix` may edit), then the guardrails lane; it exits
    non-zero if either leg fails. `make lint` carries no guardrails; the
    guardrails lane carries no native tools.
11. **File-scoped vs full-run lives behind each leg.** On file-scoped runs the
    make leg gets a NUL-delimited `FILES_FROM` and the lane gets the scoped
    paths; on full runs neither is scoped. Because the make leg's paths travel
    in a NUL file (not a command line), a filename with spaces or shell
    metacharacters cannot word-split or inject a make goal. Repo-wide doc-index
    cross-reference validation runs inside the guardrails lane on full runs, so
    an agent's scoped lint never fails on another agent's in-flight docs.

12. **Ownership is declared, never inferred.** A path with no live declaration is
    unowned — that is a fact about the record, not a judgment about the work.
    Undeclared dirt is expected from a human editing the branch directly, and no
    surface infers a claimant for it.
13. **A commit clears the declarations it carried.** A committed path's
    declaration ends at that commit; a later `telec code add` creates a new one.
    An uncommitted declaration stays live for as long as its session does.

## Primary flows

### Worktree flow

```
telec code lint (no args, worktree detected)
  → resolve dirty paths once
  → make lint FILES_FROM=<nul tempfile of existing dirty paths>   (native leg)
  → guardrails lane over the same dirty paths                     (policy leg)
```

```
telec code test (no args)
  → make test (unscoped — no 1:1 source→test map)
```

<!-- planned-change:fix-stop-checkpoint-repeats-a-commit-instruc -->
```
telec code commit (worktree detected)
  → resolve dirty paths once
  → git add dirty paths, including deletions
  → quality_paths = staged set filtered to existing files
  → handle_format(quality_paths)                          (in-process, no stash)
  → handle_lint(quality_paths)                            (in-process, no stash)
  → git commit --no-verify
```
<!-- change:fix-stop-checkpoint-repeats-a-commit-instruc -->
```
telec code commit (worktree detected)
  → resolve dirty paths once
  → read the acting session's job from its record
  → writer job:  staging set = dirty paths, including deletions
    other job:   staging set = live declarations ∩ dirty paths
  → git add the staging set
  → quality_paths = staged set filtered to existing files
  → handle_format(quality_paths)                          (in-process, no stash)
  → handle_lint(quality_paths)                            (in-process, no stash)
  → git commit --no-verify
```
<!-- /planned-change:fix-stop-checkpoint-repeats-a-commit-instruc -->


### Shared branch flow (session available)

```
telec code lint (no args, not a worktree, session identity present)
  → resolve dirty paths once
  → intersect dirty files with the session's live declarations
  → validate paths
  → make lint FILES_FROM=<nul tempfile of scoped paths>  +  guardrails lane <scoped>
```

```
telec code commit (not a worktree, session identity present)
  → resolve dirty paths once
  → declared set = live declarations ∩ dirty paths  (--only narrows it)
  → git add the declared set, including deletions
  → quality_paths = declared set filtered to existing files
  → handle_format / handle_lint                           (in-process, no stash)
  → git commit --no-verify
  → clear the declarations this commit carried
```

### Shared branch flow (no session)

```
telec code lint (no args, not a worktree, no session identity)
  → make lint (no FILES_FROM) + guardrails lane (repo-wide) — the full suite
```

### Explicit files flow

```
telec code lint <files...>
  → skip scoping; validate paths
  → make lint FILES_FROM=<nul tempfile of provided files>  +  guardrails lane <files>
```

### Batch ownership flow

```
telec code owners <path>...
  → validate and normalize every requested project-relative dirty path
  → capture one open local-project session snapshot and one dirty-path set
  → read each snapshot session's live declarations
  → group declaring sessions by path
  → emit one complete JSON object in caller path order, including null owners
```

### Thin hook flow

```
raw git commit (partial-staging backstop)
  → .git/hooks/pre-commit (thin telec-owned guard)
  → NUL-safe Python partial-staging check only
  → exits non-zero if staged + unstaged overlap detected
  → quality gates NOT re-run (they ran in-process via telec code commit)
```

### Full-run flow

```
telec code lint --all   (or CI, no-session shared branch)
  → make lint (no FILES_FROM) + guardrails lane (repo-wide)
  → doc-index cross-reference validation runs inside the guardrails lane
```

## Failure modes

### Workspace scope unavailable

Git status, session identity, or declaration collection fails while resolving
workspace scope.

**Response:** Exit non-zero. Error message includes actionable guidance:
`Workspace scope unavailable. Pass files explicitly: telec code lint <files...>`

No silent fallback to a broader scope.

### No session identity on shared branch

No `teleclaude_identity.json` present. This is a human or CI context.

**Response:** Both legs run the full suite. Expected behavior for manual runs.

### A scoped operation runs with nothing declared

A session invokes `telec code commit` or a scoped `telec code lint` while holding
no live declarations of its own.

**Response:** Report it rather than succeeding silently. A scoped run over an
empty set that reads as a pass, and a commit that records nothing, are the two
outcomes that must never look like success. The condition reads only the acting
session's own declarations. It inspects no other path's provenance, so dirt this
session did not declare — a human's direct edits among it — never triggers it.

### Batch ownership cannot be completed

An input path is outside the project or not dirty in the captured porcelain
set, or the session snapshot or dirty-path set cannot be resolved.

**Response:** Exit non-zero with a path- or snapshot-specific diagnostic and no
ownership JSON.

### No recognised language artifacts / missing make target

`make lint` has nothing to run, or the project has no `Makefile` target to
delegate to.

**Response:** `make` reports the missing target; `telec code <verb>` surfaces it
and points at the project-toolchain assessment to wire the target up.
