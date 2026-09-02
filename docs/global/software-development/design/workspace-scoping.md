---
description: "How telec code commands resolve workspace scope and compose the project's native make targets with the TeleClaude guardrails lane across isolated worktrees, shared branches, and explicit file overrides."
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
   uncommitted work. Scope to the current session's touched dirty files.
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
(the commit pathspec filtered to existing files) before `git commit --no-verify`.
No framework stash, no working-tree reset outside the pathspec. The installed
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

| Input              | Source                                                                                                                                   |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Execution context  | `resolve_workspace_scope_resolution()`                                                                                                   |
| Session identity   | `$TMPDIR/teleclaude_identity.json`                                                                                                       |
| Session transcript | Daemon transcript for the current session                                                                                                |
| Dirty paths        | `git status --porcelain --untracked-files=all`                                                                                           |
| Project languages  | Detected from repo artifacts (`pyproject.toml`, `setup.py`, root Python files, `tsconfig.json`, TypeScript `package.json`, `Cargo.toml`) |
| Explicit file list | CLI arguments (`telec code lint <files...>`)                                                                                             |

<!-- planned-change:distinguish-undetermined-scope-from-empty-scope -->

| Output                  | Description                                                                                                |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- |
| `dirty_paths`           | Full dirty set from one porcelain parse, including operation kind                                          |
| `scoped_dirty_paths`    | Workspace-owned dirty paths, including deletions, safe for commit staging                                  |
| `scoped_existing_paths` | Workspace-owned existing paths — serialized into `FILES_FROM` (make leg) and passed to the guardrails lane |

<!-- change:distinguish-undetermined-scope-from-empty-scope -->

| Output                  | Description                                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `dirty_paths`           | Full dirty set from one porcelain parse, including operation kind                                                  |
| `scoped_dirty_paths`    | Workspace-owned dirty paths, including deletions, safe for commit staging                                          |
| `scoped_existing_paths` | Workspace-owned existing paths — serialized into `FILES_FROM` (make leg) and passed to the guardrails lane         |
| `touched_signal`        | Whether the session's touched-path set was resolved or could not be determined at all (`RESOLVED`, `UNDETERMINED`) |

<!-- /planned-change:distinguish-undetermined-scope-from-empty-scope -->

<!-- planned:telec-code-dirty-path-owners -->
### Batch dirty-path ownership

The read-only `telec code owners <path>...` query resolves custodianship for a
caller-supplied batch of project-relative dirty paths. Its inputs are the
validated paths, one porcelain-derived dirty set, and one snapshot of open
sessions whose project root and computer match the caller. Closed sessions are
outside the snapshot.

The `agent_runtime` attribution query owns a dedicated foreign-session resolver
that returns timestamp-preserving path-attribution evidence and a closed
`RESOLVED` / `UNDETERMINED` signal. It consumes the captured session row's
`active_agent`, `native_log_file`, and `native_session_id` before invoking the
agent-native parser. For Codex it uses `native_log_file` when present and
otherwise resolves `native_session_id` through
`discover_codex_transcript_path()`; it never consults the caller process's
`CODEX_THREAD_ID` or `discover_current_codex_transcript_path()`. Missing,
unreadable, malformed, unsupported, or otherwise unresolvable foreign-session
evidence is `UNDETERMINED`; a successfully parsed transcript with no qualifying
touch is `RESOLVED` empty. This batch signal is defined independently of the
quality scope's current-session command model.

The query resolves each requested path's last committed boundary once from
repository history, without inspecting commit authorship, and discards touch
evidence at or before that boundary. It then intersects the surviving evidence
with the captured dirty set, selects the live claimant with the earliest
surviving touch timestamp, and uses session UUID only as the deterministic
tie-breaker. A path with no commit history has no boundary. All snapshot
sessions are resolved in parallel; the candidate set is never refreshed during
one query invocation.

The output is one JSON object keyed by every requested path. An owned entry
carries the TeleClaude session UUID, job role, and title; a path with no
claimant in the completed snapshot carries `null`. Attribution evidence is
ephemeral query data: no ownership ledger, git-author inference, or durable
claim state is introduced.

A live session whose governed transcript attribution resolves empty contributes
no claimant evidence. A session whose attribution signal is `UNDETERMINED` also
contributes no invented claim, but the query carries a privacy-safe batch-level
`undetermined_session_count` diagnostic. The CLI emits that count on stderr and
the structured completion record while leaving the stdout ownership JSON
unchanged. When the count is positive, null transfers inspection custodianship
only: the integrator may preserve discernible intent in a commit, but it cannot
classify residue as abandoned or revert it on the strength of that invocation's
null result. A later reminder beat runs a fresh query over a fresh open-session
snapshot. Destructive null-custody authority returns only when that fresh result
reports zero undetermined sessions and no live claimant for the path. Snapshot
acquisition, dirty-set resolution, and path validation remain structural query
boundaries and fail the batch when they cannot complete.
<!-- /planned:telec-code-dirty-path-owners -->

## Invariants

1. **No stashing.** The scoping mechanism keeps files outside the agent's scope untouched, so there is never a need to stash anything aside.
2. **Worktrees are task-scoped.** A worktree is isolated — all dirty files
   belong to the task. Existing dirty files drive both legs and the
   commit-staging set; commit staging may also include deleted dirty paths.
3. **Shared branches are session-scoped.** On a shared branch, only files the
   current session touched and that are dirty are scoped. This prevents agents
   from linting or committing other agents' in-progress work.
4. **Explicit files override everything.** When the caller passes files as
   arguments, scoping is skipped and those files drive both legs.
5. **Commit gates run in-process, no stash.** `telec code commit` runs format
   then lint against `quality_paths` before `git commit --no-verify`; the thin
   `.git/hooks/pre-commit` performs only a partial-staging backstop. No
   framework stash, no working-tree reset outside the commit pathspec.

<!-- planned-change:distinguish-undetermined-scope-from-empty-scope -->

6. **Scope failure is an error.** If workspace scope cannot be resolved and no
   explicit files are provided, the command exits non-zero with guidance:
   "pass files explicitly." It never silently falls back to a broader scope.

<!-- change:distinguish-undetermined-scope-from-empty-scope -->

6. **Scope failure is an error.** If workspace scope resolution itself fails —
   git status errors or an unexpected transcript-collection failure — and no
   explicit files are provided, the command exits non-zero with guidance:
   "pass files explicitly." It never silently falls back to a broader scope.
   An unbound session transcript is not a scope failure: it resolves to an
   empty scope with `touched_signal` `UNDETERMINED` and is reported per
   invariant 12.

<!-- /planned-change:distinguish-undetermined-scope-from-empty-scope -->

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

<!-- planned:distinguish-undetermined-scope-from-empty-scope -->

12. **Undetermined scope is never reported as empty scope.** A session whose
    transcript is not resolvable yields no touched-path signal, and its scope
    resolves empty with `touched_signal` set to `UNDETERMINED`. A session that
    owns a transcript and touched no dirty path resolves empty with
    `touched_signal` set to `RESOLVED`. Every `telec code` verb that reports an
    empty scope distinguishes the two: on `UNDETERMINED` it states that the
    scope could not be determined rather than asserting there is nothing to do.
    The unbound transcript is an expected early-session condition, and the
    agent_stop checkpoint runs with a bound transcript, so every undetermined
    diagnostic directs the agent to continue working and let the end-of-turn
    checkpoint re-resolve the scope. `telec code commit` additionally names
    `--include` and `--only` as the channels for committing immediately; no
    other verb names an immediate declaration channel — for `telec code
changed` and `telec code lint` the checkpoint guidance is the whole
    recovery pointer. Worktree scope and no-session-identity shared-branch
    scope are always `RESOLVED` — neither consults the transcript.

<!-- /planned:distinguish-undetermined-scope-from-empty-scope -->

<!-- planned:telec-code-dirty-path-owners -->
13. **Null means no usable live claimant, not proof of abandonment.** A captured
    session with resolved-empty or `UNDETERMINED` batch attribution contributes
    no claim. `UNDETERMINED` is reported through the batch-level count and
    prohibits destructive null-custody resolution for that query result. A
    later fresh query may restore that authority only after the count reaches
    zero. Invalid paths or a failure to capture the session snapshot or dirty
    set fail the query instead of producing a partial map.
14. **A commit clears earlier claims.** Touch evidence at or before a path's
    last committed boundary is ineligible even when its session remains open.
    A later uncommitted touch creates a new claim from that later timestamp.
<!-- /planned:telec-code-dirty-path-owners -->

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

```
telec code commit (worktree detected)
  → resolve dirty paths once
  → git add dirty paths, including deletions
  → quality_paths = pathspec filtered to existing files
  → handle_format(quality_paths)                          (in-process, no stash)
  → handle_lint(quality_paths)                            (in-process, no stash)
  → git commit --no-verify
```

```
telec code changed (worktree detected)
  → resolve dirty paths once
  → print dirty paths, including deletions
```

### Shared branch flow (session available)

```
telec code lint (no args, not a worktree, session identity present)
  → resolve dirty paths once
  → intersect dirty files with session-touched files from transcript
  → validate paths
  → make lint FILES_FROM=<nul tempfile of scoped paths>  +  guardrails lane <scoped>
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

<!-- planned:telec-code-dirty-path-owners -->
### Batch ownership flow

```
telec code owners <path>...
  → validate and normalize every requested project-relative dirty path
  → capture one open local-project session snapshot and one dirty-path set
  → resolve one last-commit boundary per requested path without author inspection
  → resolve timestamped session-scoping evidence for snapshot sessions in parallel
  → carry the count of sessions whose attribution signal is UNDETERMINED
  → discard touches at or before each path's commit boundary
  → group surviving candidates by path and select (touch_at, session_uuid) minimum
  → emit one complete JSON object in caller path order, including null owners
```
<!-- /planned:telec-code-dirty-path-owners -->

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

<!-- planned-change:distinguish-undetermined-scope-from-empty-scope -->

### Workspace scope unavailable

Git status, session identity, or transcript collection fails while resolving
workspace scope.

**Response:** Exit non-zero. Error message includes actionable guidance:
`Workspace scope unavailable. Pass files explicitly: telec code lint <files...>`

No silent fallback to a broader scope.

<!-- change:distinguish-undetermined-scope-from-empty-scope -->

### Workspace scope unavailable

Git status fails, or transcript collection fails unexpectedly, while resolving
workspace scope.

**Response:** Exit non-zero. Error message includes actionable guidance:
`Workspace scope unavailable. Pass files explicitly: telec code lint <files...>`

No silent fallback to a broader scope.

### Session transcript not yet bound

The session exists but no transcript is bound yet, so the touched-path set
cannot be determined. This is an expected early-session condition, not an
error.

**Response:** Scope resolves empty with `touched_signal` `UNDETERMINED`, and
each verb reports per invariant 12: the truth (scope undetermined, not empty)
plus checkpoint-first guidance; `telec code commit` additionally names
`--include`/`--only` for committing immediately. `telec code lint` prints the
undetermined notice and returns without running either leg.

<!-- /planned-change:distinguish-undetermined-scope-from-empty-scope -->

### No session identity on shared branch

No `teleclaude_identity.json` present. This is a human or CI context.

**Response:** Both legs run the full suite. Expected behavior for manual runs.

<!-- planned:telec-code-dirty-path-owners -->
### Batch ownership cannot be completed

An input path is outside the project or not dirty in the captured porcelain
set, or the session snapshot, dirty-path set, or commit boundary cannot be
resolved.

**Response:** Exit non-zero with a path- or snapshot-specific diagnostic and no
ownership JSON. An unavailable per-session transcript is not this failure: that
session contributes no claimant evidence under the governed scope contract.
<!-- /planned:telec-code-dirty-path-owners -->

### No recognised language artifacts / missing make target

`make lint` has nothing to run, or the project has no `Makefile` target to
delegate to.

**Response:** `make` reports the missing target; `telec code <verb>` surfaces it
and points at the project-toolchain assessment to wire the target up.
