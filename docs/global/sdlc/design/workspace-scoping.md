---
description: "How telec's repository commands resolve workspace scope from session declarations and compose the project's native make targets with the TeleClaude guardrails lane across isolated worktrees, shared branches, and explicit file overrides."
visibility: 'public'
---

# Workspace Scoping — Design

## Purpose

<!-- planned-change:telec-repo-command-family -->

`telec code` commands run from isolated worktrees, shared branches, human shells,
and CI. Workspace scoping decides which paths belong to the current operation
without stashing and without touching another agent's in-progress files.

`telec code` is the scoping and composition layer. It resolves which files the
current operation owns, then delegates execution — it embeds no toolchain of its
own. `telec code lint` composes **two decoupled legs**:

<!-- change:telec-repo-command-family -->

`telec repo` commands run from isolated worktrees, shared branches, human shells,
and CI. Workspace scoping decides which paths belong to the current operation
without stashing and without touching another agent's in-progress files.

`telec repo` is the scoping and composition layer. It resolves which files the
current operation owns, then delegates execution — it embeds no toolchain of its
own. `telec repo lint` composes **two decoupled legs**:

<!-- /planned-change:telec-repo-command-family -->

1. the project's own `make lint` — native tools (ruff/pyright/mypy/jscpd, eslint/tsc,
   cargo) with **zero TeleClaude dependency**; and
2. TeleClaude's own checks — its code rules, snippet validation, and artifact
   validation — each run only where the owning home carries the capability it
   belongs to: `code`, `docs`, or `agents` in that home's `teleclaude.yml`.

<!-- planned-change:telec-repo-command-family -->

`make lint` never contains the guardrails lane and never calls `telec`; the
guardrails lane is never plumbed into any `Makefile`. The native Makefile shape
is identical for TeleClaude's own repo and any adopting project, while the
current guardrails lane remains TeleClaude-repo-rooted.
`telec code format` resolves the same workspace scope as `telec code lint` and
hands it to `make format` the same way; the explicit full-run option sweeps
everything.
`telec code test|install` are pure delegations to `make test|install`.

<!-- change:telec-repo-command-family -->

`make lint` never contains the guardrails lane and never calls `telec`; the
guardrails lane is never plumbed into any `Makefile`. The native Makefile shape
is identical for TeleClaude's own repo and any adopting project, while the
current guardrails lane remains TeleClaude-repo-rooted.
`telec repo format` resolves the same workspace scope as `telec repo lint` and
hands it to `make format` the same way; the explicit full-run option sweeps
everything.
`telec repo test|install` are pure delegations to `make test|install`.

<!-- /planned-change:telec-repo-command-family -->

Three execution contexts drive file resolution:

1. **Worktree** — isolated by design. All dirty paths in the worktree belong to
   the task.
2. **Shared branch with session identity** — multiple agents may have
   uncommitted work. Scope to the current session's declared dirty files.
3. **Shared branch without session identity** — human or CI context. Lint
   makes a full run (Invariant 11).
4. **Explicit files** — caller passes file arguments directly. Skip workspace
   scoping.

<!-- planned-change:telec-repo-command-family -->

`make lint` and `make test` are the project's own entrypoints; they run native
tools directly and do NOT call back into `telec code`. The delegation is
one-directional: `telec code lint` resolves scope and invokes `make lint`,
passing the scoped file list as a **NUL-delimited `FILES_FROM` temp file** (the
paths never travel on `make`'s command line, in `$@`/`$*`, or as a make goal),
and runs the guardrails lane over the same scoped paths. A `make lint` with no
`FILES_FROM` runs the whole suite. There is no `telec code → make → telec code`
cycle.

`telec code commit` formats `quality_paths` (the declared set filtered to
existing files) and then runs `git commit`. The installed `.git/hooks/pre-commit`
runs `telec code pre-commit`, which is the commit gate for every route into a
commit: the partial-staging guard, then lint over the staged file set. No
framework stash, no working-tree reset outside the declared set.

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

<!-- change:telec-repo-command-family -->

`make lint` and `make test` are the project's own entrypoints; they run native
tools directly and do NOT call back into `telec repo`. The delegation is
one-directional: `telec repo lint` resolves scope and invokes `make lint`,
passing the scoped file list as a **NUL-delimited `FILES_FROM` temp file** (the
paths never travel on `make`'s command line, in `$@`/`$*`, or as a make goal),
and runs the guardrails lane over the same scoped paths. A `make lint` with no
`FILES_FROM` runs the whole suite. There is no `telec repo → make → telec repo`
cycle.

`telec repo commit` formats `quality_paths` (the declared set filtered to
existing files) and then runs `git commit`. The installed `.git/hooks/pre-commit`
runs `telec repo pre-commit`, which is the commit gate for every route into a
commit: the partial-staging guard, then lint over the staged file set. No
framework stash, no working-tree reset outside the declared set.

Tool invocation is separate from file scoping. `telec repo` decides which files
are in play; the `make` recipes own how the native tools run, and the guardrails
lane runs the policy scripts (as subprocess argv — argv-safe). In uv-managed
Python projects the make recipes invoke project tools through the uv-managed
entrypoints defined by the Python tooling policy.

The code owner for workspace-derived scope is
`teleclaude/quality/scope.py::resolve_workspace_scope_resolution()`. Callers may
own explicit file arguments, output rendering, staging, or fallback behavior,
but they do not branch on git worktree state directly. Each `telec repo` verb
then renders the resolved scope into a `make` invocation (and, for lint, the
guardrails lane).

<!-- /planned-change:telec-repo-command-family -->

## Inputs/Outputs

<!-- planned-change:telec-repo-command-family -->

| Input                | Source                                                                                                                                   |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Execution context    | `resolve_workspace_scope_resolution()`                                                                                                   |
| Session identity     | `$TMPDIR/teleclaude_identity.json`                                                                                                       |
| Session declarations | The session's own declaration record, written by `telec code add` and by the session's successful edit-tool calls                        |
| Dirty paths          | `git status --porcelain --untracked-files=all`                                                                                           |
| Project languages    | Detected from repo artifacts (`pyproject.toml`, `setup.py`, root Python files, `tsconfig.json`, TypeScript `package.json`, `Cargo.toml`) |
| Explicit file list   | CLI arguments (`telec code lint <files...>`)                                                                                             |

<!-- change:telec-repo-command-family -->

| Input                | Source                                                                                                                                   |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Execution context    | `resolve_workspace_scope_resolution()`                                                                                                   |
| Session identity     | `$TMPDIR/teleclaude_identity.json`                                                                                                       |
| Session declarations | The session's own declaration record, written by `telec repo add` and by the session's successful edit-tool calls                        |
| Dirty paths          | `git status --porcelain --untracked-files=all`                                                                                           |
| Project languages    | Detected from repo artifacts (`pyproject.toml`, `setup.py`, root Python files, `tsconfig.json`, TypeScript `package.json`, `Cargo.toml`) |
| Explicit file list   | CLI arguments (`telec repo lint <files...>`)                                                                                             |

<!-- /planned-change:telec-repo-command-family -->

| Output                  | Description                                                                                                |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- |
| `dirty_paths`           | Full dirty set from one porcelain parse, including operation kind                                          |
| `scoped_dirty_paths`    | Workspace-owned dirty paths, including deletions, safe for commit staging                                  |
| `scoped_existing_paths` | Workspace-owned existing paths — serialized into `FILES_FROM` (make leg) and passed to the guardrails lane |

### Session path declarations

On a shared branch, session-owned path evidence is exactly the set of paths the
session declared. A declaration is an entry in the declaring session's own
record, carrying the path and the instant it was declared. Two acts write one:

<!-- planned-change:telec-repo-command-family -->

- a successful `telec code add`, which accepts paths that are clean or do not
  yet exist — declaring is bookkeeping and carries no git state of its own; and
- a successful call to an edit tool whose own input names the file it writes,
  declared by the hook receiver when the runtime reports that call's success.
  Session scoping owns, per runtime, which tools qualify and which input field
  names the file. A failed call declares nothing, and a path outside the
  session's checkout is never declared.

Either act writes the record directly, so the shell form of an invocation, the
agent runtime that ran it, and the readability of the session's transcript are
all outside the evidence path. A declaration is live from the moment it is
written until the commit that carries it lands and clears it; `--only` clears
just the subset that commit carried. Shell-command text and transcript reading
never write a declaration: they only raise the advisory questions described
below, which a session answers with `telec code add`.

<!-- change:telec-repo-command-family -->

- a successful `telec repo add`, which accepts paths that are clean or do not
  yet exist — declaring is bookkeeping and carries no git state of its own; and
- a successful call to an edit tool whose own input names the file it writes,
  declared by the hook receiver when the runtime reports that call's success.
  Session scoping owns, per runtime, which tools qualify and which input field
  names the file. A failed call declares nothing, and a path outside the
  session's checkout is never declared.

Either act writes the record directly, so the shell form of an invocation, the
agent runtime that ran it, and the readability of the session's transcript are
all outside the evidence path. A declaration is live from the moment it is
written until the commit that carries it lands and clears it; `--only` clears
just the subset that commit carried. Shell-command text and transcript reading
never write a declaration: they only raise the advisory questions described
below, which a session answers with `telec repo add`.

<!-- /planned-change:telec-repo-command-family -->

The record lives in the declaring session's TeleClaude temporary directory,
beside the checkpoint flags, and is kept when that directory is emptied for a
fresh host pane. A declaration therefore stays live across an agent restart, a
handoff, a revival of the same session, and a host reboot. The record is removed
with the directory when the session closes, or when the orphan sweep reaps a
directory whose session is gone. Writes to the record are serialized, so
concurrent tool calls never lose an entry.

Every implicit-scope consumer on a shared branch reads this same evidence.
Session-scoped lint, commit, and the agent-stop checkpoint each intersect it
with the current dirty set. Scoped lint and commit continue to use the dirty
set of a worktree. At agent stop in a todo worktree, the checkpoint instead
attributes those paths only to that todo's builder or finalizer; other sessions
there owe no commit instruction for them. Worktrees outside the todo lifecycle
retain their worktree-wide checkpoint scope. The checkpoint reads the acting
session's job from its session record.

A path is **owned** when it is both declared and dirty. A declared path that is
clean is not owned and appears in no scope. Several sessions may declare the same
path; each is an owner, and no arbitration selects between them.

### Undeclared-write questions

A shell write leaves no declaration. At agent stop on a shared branch, the
checkpoint names the dirty paths that match the session's own shell activity in
the current checkpoint cycle and that the session has not declared, and asks the
session to declare the ones that are its own. A path matches when it is a write
target of a successful shell command: a redirection destination, a path a
file-writing command creates, modifies, or removes, or a path named in the
destination expression of a recognized write call in an interpreter script,
including the single assignment that binds a destination name. A path the
command only reads or only carries as data, including write content, matches
nothing, and neither do
read-only commands and read-only tools. The question is advice: it adds
nothing to scope, writes no declaration, and gates no commit. The session
remains the only party that knows whether it wrote the file.

### Ownership query

<!-- planned-change:telec-repo-command-family -->

`telec code owners` reports, for every dirty path of the project's canonical
checkout, the live sessions that declared it, or none. It resolves the dirty set
itself, takes no path arguments, and answers for the canonical checkout from
wherever in the project it is invoked. Several declaring sessions are all
reported; no arbitration selects between them. A path with no live declaration
is reported as unowned; who may have written it is the caller's question to
answer from session history.

<!-- change:telec-repo-command-family -->

`telec repo owners` reports, for every dirty path of the project's canonical
checkout, the live sessions that declared it, or none. It resolves the dirty set
itself, takes no path arguments, and answers for the canonical checkout from
wherever in the project it is invoked. Several declaring sessions are all
reported; no arbitration selects between them. A path with no live declaration
is reported as unowned; who may have written it is the caller's question to
answer from session history.

<!-- /planned-change:telec-repo-command-family -->

## Invariants

<!-- planned-change:telec-repo-command-family -->

1. **No stashing.** The scoping mechanism keeps files outside the agent's scope untouched, so there is never a need to stash anything aside.
2. **Worktrees are task-scoped.** A worktree is isolated — all dirty files
   belong to the task. Existing dirty files drive both legs and the
   commit-staging set; commit staging may also include deleted dirty paths.
3. **Shared branches are declaration-scoped.** On a shared branch, only files the
   current session declared and that are dirty are scoped. This prevents agents
   from linting or committing other agents' in-progress work.
4. **Explicit files override everything.** When the caller passes files as
   arguments, scoping is skipped and those files drive both legs.
5. **The pre-commit hook is the commit gate, no stash.** `telec code commit`
   formats `quality_paths`, then runs `git commit`, and git runs
   `.git/hooks/pre-commit`. The hook applies the partial-staging guard, then
   lints the staged file set, the same way for every route into a commit. It
   checks formatting and never rewrites a file, and selects checks by each
   staged path's owning home. The documentation and agent-artifact validators
   read the staged content against the rest of each owning home as committed;
   the native leg runs on disk over the staged files, which the partial-staging
   guard makes identical to what is staged. No framework stash, no working-tree
   reset outside the declared set.

6. **Scope failure is an error.** If workspace scope cannot be resolved and no
   explicit files are provided, the command exits non-zero with guidance:
   "pass files explicitly." It never silently falls back to a broader scope.

7. **No session identity on a shared branch means full run.** Human and CI
   contexts have no session identity; lint makes a full run (Invariant 11).
8. **Tool environment is owned by make and the lane.** Scoping decides what to
   check; the project's `make` recipes own the native tool environment, and the
   guardrails lane owns the policy scripts. `telec code` invokes no tool of its
   own.
9. **`make test` is never file-scoped.** The spec-anchored model has no 1:1
   source→test map, so `telec code test` delegates to `make test` with no scope.
10. **Preparation precedes concurrent checking; both legs block.** Any scoped
    formatting and staged-content materialization finish before lint reads the
    selected inputs. Formatting and dependency preparation belong to their
    separate Make targets under `sdlc/design/project-toolchain`; native lint
    checks the prepared sources without rewriting them. Native lint and the
    guardrails lane may overlap, and independent guardrail stages use bounded
    concurrency. Owning homes complete one at a time. Selected roots, paths,
    capabilities and environments remain attached to their checks. All selected
    checks finish before success is reported; either leg's failure blocks, with
    failure selection in declared order rather than completion order.
    Cancellation and unexpected failure join running checks and reap their
    command groups before releasing grading resources. `make lint` carries no
    guardrails; the guardrails lane carries no native tools.
11. **File-scoped vs full-run lives behind each check.** On file-scoped runs
    the make leg gets a NUL-delimited `FILES_FROM` and TeleClaude's checks get
    the scoped paths. A full run collects the homes in the repository's
    committed tree and runs, per home, exactly the checks that home's
    capabilities carry over every file of that home git does not ignore: the make leg without
    `FILES_FROM` at a home carrying `code`, so the project's own lint defines
    its full suite, and TeleClaude's checks over those files,
    whole-home doc-index cross-reference validation included. The full-run
    option widens the files, never the checks: content git ignores, and another
    repository nested inside the repository, are never graded, and a home that
    carries no capability is not checked. Because the make leg's paths travel
    in a NUL file (not a command line), a filename with spaces or shell
    metacharacters cannot word-split or inject a make goal. Whole-home
    cross-reference validation runs only on full runs, so an agent's scoped
    lint never fails on another agent's in-flight docs.

12. **Ownership is declared, never inferred.** A path with no live declaration is
    unowned — that is a fact about the record, not a judgment about the work.
    Undeclared dirt is expected from a human editing the branch directly. A
    suggested writer — the checkpoint's question, or a lookup in session
    history — is advice to a session and never makes it an owner; only a
    declaration does.
    These declarations scope `telec code` operations only; they do not set or
    confine file-edit targets. In a worktree, edit targets are resolved beneath
    the active worktree root as required by `sdlc/policy/version-control-safety`.
13. **A commit clears the declarations it carried.** A committed path's
    declaration ends at that commit; a later `telec code add` creates a new one.
    An uncommitted declaration stays live for as long as its session does.

<!-- change:telec-repo-command-family -->

1. **No stashing.** The scoping mechanism keeps files outside the agent's scope untouched, so there is never a need to stash anything aside.
2. **Worktrees are task-scoped.** A worktree is isolated — all dirty files
   belong to the task. Existing dirty files drive both legs and the
   commit-staging set; commit staging may also include deleted dirty paths.
3. **Shared branches are declaration-scoped.** On a shared branch, only files the
   current session declared and that are dirty are scoped. This prevents agents
   from linting or committing other agents' in-progress work.
4. **Explicit files override everything.** When the caller passes files as
   arguments, scoping is skipped and those files drive both legs.
5. **The pre-commit hook is the commit gate, no stash.** `telec repo commit`
   formats `quality_paths`, then runs `git commit`, and git runs
   `.git/hooks/pre-commit`. The hook applies the partial-staging guard, then
   lints the staged file set, the same way for every route into a commit. It
   checks formatting and never rewrites a file, and selects checks by each
   staged path's owning home. The documentation and agent-artifact validators
   read the staged content against the rest of each owning home as committed;
   the native leg runs on disk over the staged files, which the partial-staging
   guard makes identical to what is staged. No framework stash, no working-tree
   reset outside the declared set.

6. **Scope failure is an error.** If workspace scope cannot be resolved and no
   explicit files are provided, the command exits non-zero with guidance:
   "pass files explicitly." It never silently falls back to a broader scope.

7. **No session identity on a shared branch means full run.** Human and CI
   contexts have no session identity; lint makes a full run (Invariant 11).
8. **Tool environment is owned by make and the lane.** Scoping decides what to
   check; the project's `make` recipes own the native tool environment, and the
   guardrails lane owns the policy scripts. `telec repo` invokes no tool of its
   own.
9. **`make test` is never file-scoped.** The spec-anchored model has no 1:1
   source→test map, so `telec repo test` delegates to `make test` with no scope.
10. **Preparation precedes concurrent checking; both legs block.** Any scoped
    formatting and staged-content materialization finish before lint reads the
    selected inputs. Formatting and dependency preparation belong to their
    separate Make targets under `sdlc/design/project-toolchain`; native lint
    checks the prepared sources without rewriting them. Native lint and the
    guardrails lane may overlap, and independent guardrail stages use bounded
    concurrency. Owning homes complete one at a time. Selected roots, paths,
    capabilities and environments remain attached to their checks. All selected
    checks finish before success is reported; either leg's failure blocks, with
    failure selection in declared order rather than completion order.
    Cancellation and unexpected failure join running checks and reap their
    command groups before releasing grading resources. `make lint` carries no
    guardrails; the guardrails lane carries no native tools.
11. **File-scoped vs full-run lives behind each check.** On file-scoped runs
    the make leg gets a NUL-delimited `FILES_FROM` and TeleClaude's checks get
    the scoped paths. A full run collects the homes in the repository's
    committed tree and runs, per home, exactly the checks that home's
    capabilities carry over every file of that home git does not ignore: the make leg without
    `FILES_FROM` at a home carrying `code`, so the project's own lint defines
    its full suite, and TeleClaude's checks over those files,
    whole-home doc-index cross-reference validation included. The full-run
    option widens the files, never the checks: content git ignores, and another
    repository nested inside the repository, are never graded, and a home that
    carries no capability is not checked. Because the make leg's paths travel
    in a NUL file (not a command line), a filename with spaces or shell
    metacharacters cannot word-split or inject a make goal. Whole-home
    cross-reference validation runs only on full runs, so an agent's scoped
    lint never fails on another agent's in-flight docs.

12. **Ownership is declared, never inferred.** A path with no live declaration is
    unowned — that is a fact about the record, not a judgment about the work.
    Undeclared dirt is expected from a human editing the branch directly. A
    suggested writer — the checkpoint's question, or a lookup in session
    history — is advice to a session and never makes it an owner; only a
    declaration does.
    These declarations scope `telec repo` operations only; they do not set or
    confine file-edit targets. In a worktree, edit targets are resolved beneath
    the active worktree root as required by `sdlc/policy/version-control-safety`.
13. **A commit clears the declarations it carried.** A committed path's
    declaration ends at that commit; a later `telec repo add` creates a new one.
    An uncommitted declaration stays live for as long as its session does.

<!-- /planned-change:telec-repo-command-family -->

## Primary flows

### Worktree flow

<!-- planned-change:telec-repo-command-family -->

```
telec code lint (no args, worktree detected)
  → resolve dirty paths once
  → make format FILES_FROM=<nul tempfile of existing dirty paths>
  → concurrently: make lint FILES_FROM=<nul tempfile> + guardrails over the same paths
  → join the checks and report their ordered outcomes
```

```
telec code test (no args)
  → make test (unscoped — no 1:1 source→test map)
```

```
telec code commit (worktree detected)
  → resolve dirty paths once
  → git add dirty paths, including deletions
  → quality_paths = staged set filtered to existing files
  → handle_format(quality_paths)                          (before committing, no stash)
  → git commit
    → .git/hooks/pre-commit → telec code pre-commit (partial-staging guard, lint staged set)
```

<!-- change:telec-repo-command-family -->

```
telec repo lint (no args, worktree detected)
  → resolve dirty paths once
  → make format FILES_FROM=<nul tempfile of existing dirty paths>
  → concurrently: make lint FILES_FROM=<nul tempfile> + guardrails over the same paths
  → join the checks and report their ordered outcomes
```

```
telec repo test (no args)
  → make test (unscoped — no 1:1 source→test map)
```

```
telec repo commit (worktree detected)
  → resolve dirty paths once
  → git add dirty paths, including deletions
  → quality_paths = staged set filtered to existing files
  → handle_format(quality_paths)                          (before committing, no stash)
  → git commit
    → .git/hooks/pre-commit → telec repo pre-commit (partial-staging guard, lint staged set)
```

<!-- /planned-change:telec-repo-command-family -->

### Shared branch flow (session available)

<!-- planned-change:telec-repo-command-family -->

```
telec code lint (no args, not a worktree, session identity present)
  → resolve dirty paths once
  → intersect dirty files with the session's live declarations
  → validate paths
  → make format FILES_FROM=<nul tempfile of scoped paths>
  → concurrently: make lint FILES_FROM=<nul tempfile> + guardrails lane <scoped>
  → join the checks and report their ordered outcomes
```

```
telec code commit (not a worktree, session identity present)
  → resolve dirty paths once
  → declared set = live declarations ∩ dirty paths  (--only narrows it)
  → git add the declared set, including deletions
  → quality_paths = declared set filtered to existing files
  → handle_format(quality_paths)                          (before committing, no stash)
  → git commit
    → .git/hooks/pre-commit → telec code pre-commit (partial-staging guard, lint staged set)
  → clear the declarations this commit carried
```

<!-- change:telec-repo-command-family -->

```
telec repo lint (no args, not a worktree, session identity present)
  → resolve dirty paths once
  → intersect dirty files with the session's live declarations
  → validate paths
  → make format FILES_FROM=<nul tempfile of scoped paths>
  → concurrently: make lint FILES_FROM=<nul tempfile> + guardrails lane <scoped>
  → join the checks and report their ordered outcomes
```

```
telec repo commit (not a worktree, session identity present)
  → resolve dirty paths once
  → declared set = live declarations ∩ dirty paths  (--only narrows it)
  → git add the declared set, including deletions
  → quality_paths = declared set filtered to existing files
  → handle_format(quality_paths)                          (before committing, no stash)
  → git commit
    → .git/hooks/pre-commit → telec repo pre-commit (partial-staging guard, lint staged set)
  → clear the declarations this commit carried
```

<!-- /planned-change:telec-repo-command-family -->

### Shared branch flow (no session)

<!-- planned-change:telec-repo-command-family -->

```
telec code lint (no args, not a worktree, no session identity)
  → a full run, as in the Full-run flow
```

<!-- change:telec-repo-command-family -->

```
telec repo lint (no args, not a worktree, no session identity)
  → a full run, as in the Full-run flow
```

<!-- /planned-change:telec-repo-command-family -->

### Explicit files flow

<!-- planned-change:telec-repo-command-family -->

```
telec code lint <files...>
  → skip scoping; validate paths
  → make format FILES_FROM=<nul tempfile of provided files>
  → concurrently: make lint FILES_FROM=<nul tempfile> + guardrails lane <files>
  → join the checks and report their ordered outcomes
```

<!-- change:telec-repo-command-family -->

```
telec repo lint <files...>
  → skip scoping; validate paths
  → make format FILES_FROM=<nul tempfile of provided files>
  → concurrently: make lint FILES_FROM=<nul tempfile> + guardrails lane <files>
  → join the checks and report their ordered outcomes
```

<!-- /planned-change:telec-repo-command-family -->

### Hook gate flow

<!-- planned-change:telec-repo-command-family -->

```
git commit (raw, or invoked by telec code commit)
  → .git/hooks/pre-commit → telec code pre-commit
  → partial-staging check: exits non-zero if staged + unstaged overlap detected
  → lint the staged file set with the checks each path's owning home carries
    (independent checks may overlap after preparation; formatting checked,
    never rewritten; documentation and agent-artifact
    validators read the staged content against the rest of each owning home
    as committed; the native leg runs on disk over the staged files)
  → exits non-zero on any finding; git produces no commit
```

<!-- change:telec-repo-command-family -->

```
git commit (raw, or invoked by telec repo commit)
  → .git/hooks/pre-commit → telec repo pre-commit
  → partial-staging check: exits non-zero if staged + unstaged overlap detected
  → lint the staged file set with the checks each path's owning home carries
    (independent checks may overlap after preparation; formatting checked,
    never rewritten; documentation and agent-artifact
    validators read the staged content against the rest of each owning home
    as committed; the native leg runs on disk over the staged files)
  → exits non-zero on any finding; git produces no commit
```

<!-- /planned-change:telec-repo-command-family -->

### Full-run flow

<!-- planned-change:telec-repo-command-family -->

```
telec code lint --all   (or CI, no-session shared branch)
  → collect the homes in the repository's committed tree
  → per home, over its files git does not ignore: the checks its capabilities carry
    (code → make lint at the home root plus TeleClaude's code rules;
     docs → snippet validation; agents → artifact validation)
  → homes complete sequentially; independent read-only checks overlap and are joined
  → a home that carries no capability is not checked
```

<!-- change:telec-repo-command-family -->

```
telec repo lint --all   (or CI, no-session shared branch)
  → collect the homes in the repository's committed tree
  → per home, over its files git does not ignore: the checks its capabilities carry
    (code → make lint at the home root plus TeleClaude's code rules;
     docs → snippet validation; agents → artifact validation)
  → homes complete sequentially; independent read-only checks overlap and are joined
  → a home that carries no capability is not checked
```

<!-- /planned-change:telec-repo-command-family -->

## Failure modes

### Workspace scope unavailable

Git status, session identity, or declaration collection fails while resolving
workspace scope.

<!-- planned-change:telec-repo-command-family -->

**Response:** Exit non-zero. Error message includes actionable guidance:
`Workspace scope unavailable. Pass files explicitly: telec code lint <files...>`

<!-- change:telec-repo-command-family -->

**Response:** Exit non-zero. Error message includes actionable guidance:
`Workspace scope unavailable. Pass files explicitly: telec repo lint <files...>`

<!-- /planned-change:telec-repo-command-family -->

No silent fallback to a broader scope.

### No session identity on shared branch

No `teleclaude_identity.json` present. This is a human or CI context.

**Response:** Lint makes a full run (Invariant 11). Expected behavior for
manual runs.

### Full lint before the first commit

An unborn repository has no committed declaration tree from which full lint can
discover owning homes.

**Response:** Exit non-zero with guidance to pass files explicitly or commit the
initial staged set through the commit gate. The first commit still receives the
same staged-content checks.

### A scoped operation runs with nothing declared

<!-- planned-change:telec-repo-command-family -->

A session invokes `telec code commit` while holding no live declarations of its
own, or a scoped `telec code lint` or `telec code format` while none of its own
declared paths is dirty.

<!-- change:telec-repo-command-family -->

A session invokes `telec repo commit` while holding no live declarations of its
own, or a scoped `telec repo lint` or `telec repo format` while none of its own
declared paths is dirty.

<!-- /planned-change:telec-repo-command-family -->

**Response:** Report it rather than succeeding silently. A scoped run over an
empty set that reads as a pass, and a commit that records nothing, are the two
outcomes that must never look like success. The condition reads only the acting
session's own declarations. It inspects no other path's provenance, so dirt this
session did not declare — a human's direct edits among it — never triggers it.

### No recognised language artifacts / missing make target

`make lint` has nothing to run, or the project has no `Makefile` target to
delegate to.

<!-- planned-change:telec-repo-command-family -->

**Response:** `make` reports the missing target; `telec code <verb>` surfaces it
and points at the project-toolchain assessment to wire the target up.

<!-- change:telec-repo-command-family -->

**Response:** `make` reports the missing target; `telec repo <verb>` surfaces it
and points at the project-toolchain assessment to wire the target up.

<!-- /planned-change:telec-repo-command-family -->
