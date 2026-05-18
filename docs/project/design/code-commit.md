---
description: 'Design of telec code commit — the canonical agent commit command with workspace-scope staging and pathspec-scoped commits.'
domain: 'software-development'
id: 'project/design/code-commit'
scope: 'project'
type: 'design'
visibility: 'public'
---

# Code Commit — Design

## Purpose

`telec code commit` is the canonical commit interface for **autonomous agent
sessions inside tmux**. It resolves the workspace scope, stages those files,
and runs `git commit` with an explicit pathspec so the commit contains exactly
the files telec staged. The pre-commit hook owns formatting and linting inside
git's own atomicity.

The git wrapper redirects raw `git commit` to this command for tmux callers.
The pre-commit hook is the single owner of formatter restaging and the retry
when hooks modify staged files.

**Caller paths:**

There are three legitimate ways a commit happens in this repository.
`telec code commit` is one of them; the other two bypass it on purpose.

| Caller context | Command | Why telec is or isn't involved |
|---|---|---|
| Outside tmux (human shell) | `git commit ...` | The wrapper passes through to real git directly when `$TMUX` is unset. No identity check, no env var, no telec. |
| Inside tmux, autonomous agent | `telec code commit -m "..."` | Lock + workspace scope + pathspec commit. The body of this design. |
| Inside tmux, supervised one-off | `TELECLAUDE_COMMIT_APPROVED=1 git commit -- <paths>` | The wrapper's documented bypass. The human is supervising; the commit is their responsibility. Telec is not involved. |

**Wrapper-enforced intent layer:**

The git wrapper enforces the intent layer for every git invocation in a
tmux session. `telec code commit` runs on top of these guarantees:

- `git stash*` is blocked for non-integrators; `rebase.autoStash` and
  `merge.autoStash` are forced off on every wrapper-driven git call.
- `git add -A`, `git add --all`, and `git add .` are blocked on main for
  non-integrators. Staging on main requires explicit file paths.
- `git restore`, `git clean`, `git switch`, `git reset --hard|--merge|--keep`,
  and branch-switching `git checkout` are blocked.
- `git push` from main is integrator-only; `git merge`/`rebase`/`cherry-pick`
  on main require integrator role or `TELECLAUDE_COMMIT_APPROVED=1`.

## Inputs / Outputs

**Flag:** `-m <message>` — commit message (first-class, no `--` separator needed).
**Flag:** `--approved` — human-approved Path B commit on main; bypasses Path A/B/C
classification only.

All other arguments pass through to `git commit`. The literal `--` separator
is consumed by this command — telec appends its own pathspec separator before
the staged files.

**Outputs:** committed changeset, or failure with actionable diagnostics.

## Invariants

1. **Lock serialisation.** `main_branch_lock()` (flock on
   `GIT_MAIN_LOCK_PATH`) serialises the entire `_commit_under_lock` body.
   No two agents can be inside their commit phase at the same time. The
   lock auto-releases on process exit or crash.

2. **Workspace scope is authoritative.** `resolve_workspace_scope_resolution()`
   is the single owner of worktree-vs-shared-branch scope. Telec stages the
   files it returns and commits them.

3. **Pathspec on commit.** The final `git commit` runs with an explicit
   pathspec listing every staged file. Anything else in the index — concurrent
   stage from another session, crash residue from a prior failed commit — is
   **not** included in this commit. It stays staged for its owner to commit
   or for a human to clean up. Pathspec on commit is the safety primitive;
   there is no separate "foreign-staged" check.

4. **Pre-commit hook owns format + lint.** Formatting and linting run inside
   the hook, which executes inside git's own `index.lock`. Telec does not run
   a redundant pre-flight pass; that pre-flight would operate on a stale
   snapshot outside the atomicity primitive.

5. **Path A/B/C classification on main.** Non-integrator commits on main are
   classified:
   - **Path A:** all staged files non-functional + message contains `[skip ci]` → autonomous.
   - **Path B:** small functional change, human-approved → commit directly (`--approved`).
   - **Path C:** functional change + review → commit with `--approved`. If
     this patch series has no `/next-review-commits` reviewer yet, dispatch
     one. Follow-up commits for the same patch series are sent to that same
     reviewer with `telec sessions send`.

6. **Orchestrator restriction.** Orchestrators cannot commit on any branch.

7. **Wrapper redirect.** The git wrapper blocks `git commit` and directs agents
   to `telec code commit`. The wrapper retains all other safety blocks
   (stash, checkout, restore, clean, reset, push on main).

8. **Real git bypass for the inner commit.** The final `git commit` call uses
   the real git binary (via GitPython) so the wrapper's redirect does not loop
   back into telec.

## Primary flows

### Agent commit (worktree)

```
telec code commit -m "feat(scope): subject"
  → lock acquired
  → workspace scope = WORKTREE → all dirty paths
  → stage any not-already-staged
  → snapshot the staged set
  → real git commit -m "feat(scope): subject" -- <staged files>
  → pre-commit hook runs format + lint
  → lock released
```

### Agent commit on main (Path A — non-functional)

```
telec code commit -m "chore(docs): update snippets [skip ci]"
  → lock acquired
  → workspace scope = SHARED_BRANCH → scoped dirty paths
  → stage any not-already-staged
  → Path A: no functional files + [skip ci] → proceed
  → real git commit -- <staged files>
  → pre-commit hook runs format + lint
  → lock released
```

### Integration commit

The integrator's normal home is `trees/_integration/`, which is a worktree.
Same flow as "Agent commit (worktree)" above. The integrator role bypasses
Path A/B/C classification.

### Integrator's project-root sync

The integrator does not run `telec code commit` against the project-root main.
Repo-root sync after a delivery uses `git -C <project-root> ...` directly
(pull / merge / push). If the merge is blocked by a dirty working tree,
the integrator's heartbeat retries until the dirty file's owner commits via
their own session.

## Failure modes

**Lock contention.** Another agent holds the lock. `flock(LOCK_EX)` blocks
until released. No timeout — the agent waits, no exit code.

**Empty workspace scope.** Two distinct sub-cases:

- *Scope empty + nothing pre-staged.* The agent has not edited any tracked
  files yet and the index is empty. Exit code 1 — there is nothing to commit.
- *Scope empty + files pre-staged.* The transcript yielded no signal
  (integrator session, fresh shell, or a human staged files manually) but
  the index is non-empty. Telec falls back to committing exactly what is
  staged and emits a one-line stderr diagnostic
  (`telec code commit: session scope unavailable; committing N pre-staged
  file(s): ...`) so the fallback is observable rather than silent. The
  pathspec invariant still holds: only the pre-staged files are committed.

**Pre-commit hook failure.** The hook runs format and lint. If lint fails,
git aborts the commit and surfaces the hook output. Files remain staged for
the agent to fix and retry.

**Path B/C gate.** Functional files on main without human approval. Exit
with guidance. Path B: human approves with `--approved`. Path C: human
approves the commit; the agent dispatches `/next-review-commits` only when
the patch series has no reviewer yet. Follow-up commits for that patch series
are sent to the same reviewer.

## See also

- docs/global/software-development/design/workspace-scoping.md
- docs/global/software-development/policy/version-control-safety.md
