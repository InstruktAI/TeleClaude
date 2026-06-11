---
description: 'Design of telec code commit — the canonical agent commit command with workspace-scope staging and pathspec-scoped commits.'
visibility: 'public'
---

# Code Commit — Design

## Purpose

`telec code commit` is the canonical commit interface for **autonomous agent
sessions inside tmux**. It resolves the workspace scope and runs `git commit`
with an explicit pathspec.

The staging model is asymmetric and follows git's data model:

- **Modified-tracked files in scope** that are NOT partial-staged ride the
  pathspec straight from the working tree — `git commit -- <path>` records
  the working-tree version, no staging needed.
- **Partial-staged tracked files** in the commit pathspec (staged hunks +
  later working-tree delta) are BLOCKED by the partial-staging guard —
  `git commit -- <path>` would otherwise sweep unstaged hunks the agent
  did not declare into the commit. The blocking diagnostic points the
  agent at the recovery: `telec code add <path>` fully restages the file
  so the staged version matches the working tree, eliminating the
  ambiguity, after which `telec code commit` proceeds cleanly.
- **NEW (untracked) files in scope** are NOT auto-committed. The agent must
  declare them via `telec code add <path>` (sealed equivalent of `git add`)
  or `--include <path>` at commit time. This is the safety net against
  incidental temp/scratch artifacts the agent's tool calls may have created.
- **Unmerged-index files in pathspec** (post-conflict, pre-resolution-stage)
  are staged internally via `_stage_files` so the integrator's conflict
  resolution flow runs through the same sealed path.

<!-- planned:telec-code-delegates-to-make -->
Format then lint run in-process against `quality_paths` (the commit pathspec
filtered to existing files) before `git commit --no-verify`. No framework stash.
The installed `.git/hooks/pre-commit` is a thin fail-closed telec-owned guard
performing only a partial-staging check. See ADR-0036.
<!-- /planned:telec-code-delegates-to-make -->
<!-- superseded: "The pre-commit hook owns formatting and linting inside git's own atomicity. The pre-commit hook is the single owner of formatter restaging and the retry when hooks modify staged files." -->

The git wrapper redirects raw `git commit` (and `git add`) to this command
for tmux callers.

**Caller paths:**

There are two legitimate ways a commit happens in this repository.
`telec code commit` is one of them; the other is the human shell outside tmux.

| Caller context                | Command                            | Why telec is or isn't involved                                                                                  |
| ----------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Outside tmux (human shell)    | `git commit ...`                   | The wrapper passes through to real git directly when `$TMUX` is unset. No identity check, no env var, no telec. |
| Inside tmux, autonomous agent | `telec code commit --approved ...` | Lock + workspace scope + pathspec commit. The body of this design.                                              |

Inside tmux there is **no env-var bypass on `git commit`**. The wrapper
redirects every `git commit` invocation to `telec code commit` with no
override. `--include` is the only way to extend the commit pathspec beyond
the resolved workspace scope, and the agent must name every path it claims.

**Wrapper-enforced intent layer:**

The git wrapper enforces the intent layer for every git invocation in a
tmux session. `telec code commit` runs on top of these guarantees.

The full matrix of wrapper-gated operations, by role and by execution
context. Read columns left-to-right; the first column that decides the
op wins.

| Operation                                                                     | Worker (worktree or repo root)                                | Integrator (in `trees/_integration/`)  | Active merge (`MERGE_HEAD` present) | Rationale                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------- | -------------------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git status`, `git log`, `git show`, `git diff <ref>..<ref>`, `git rev-parse` | ✅ allowed                                                    | ✅ allowed                             | ✅ allowed                          | Read-only inspection.                                                                                                                                                                                                                                                                                                                                                                     |
| `git add` (any form)                                                          | ❌ blocked → `telec code add`                                 | ❌ blocked → `telec code add`          | ❌ blocked                          | Staging is telec's job; sealed-commit pathspec depends on it.                                                                                                                                                                                                                                                                                                                             |
| `git commit`                                                                  | ❌ blocked → `telec code commit`                              | ❌ blocked → `telec code commit`       | ❌ blocked                          | Sealed commit contract; no env-var bypass.                                                                                                                                                                                                                                                                                                                                                |
| `git reset HEAD <path>` / `git reset -- <path>` (pathspec)                    | ✅ allowed                                                    | ✅ allowed                             | ✅ allowed                          | Path-scoped unstage; index-only effect.                                                                                                                                                                                                                                                                                                                                                   |
| `git reset` (no pathspec)                                                     | ❌ blocked                                                    | ❌ blocked                             | ❌ blocked                          | Discards staged state non-locally.                                                                                                                                                                                                                                                                                                                                                        |
| `git reset --hard\|--merge\|--keep`                                           | ❌ blocked                                                    | ❌ blocked                             | ❌ blocked                          | Discards commits / merge state.                                                                                                                                                                                                                                                                                                                                                           |
| `git restore <path>` (working-tree revert to HEAD)                            | ✅ allowed                                                    | ⚠️ `--confirmed` required              | ⚠️ `--confirmed` required           | Same risk as `git checkout HEAD -- <path>`. Worktree-only blast radius elsewhere; in the integration worktree the working tree feeds DELIVERY_BOOKKEEPING.                                                                                                                                                                                                                                |
| `git restore --staged <path>`                                                 | ✅ allowed                                                    | ✅ allowed                             | ✅ allowed                          | Index-only effect; same as `git reset -- <path>`.                                                                                                                                                                                                                                                                                                                                         |
| `git restore --source <ref> <path>`                                           | ✅ allowed                                                    | ⚠️ `--confirmed` required              | ⚠️ `--confirmed` required           | Pulls foreign content from `<ref>` into working tree; same risk surface as `git checkout <ref> -- <path>`.                                                                                                                                                                                                                                                                                |
| `git checkout -- <path>` (no ref)                                             | ✅ allowed                                                    | ⚠️ `--confirmed` required              | ⚠️ `--confirmed` required           | Working-tree revert to HEAD; same gating as `git restore <path>`.                                                                                                                                                                                                                                                                                                                         |
| `git checkout <ref> -- <path>`                                                | ✅ allowed                                                    | ⚠️ `--confirmed` required              | ⚠️ `--confirmed` required           | Foreign-ref content into working tree.                                                                                                                                                                                                                                                                                                                                                    |
| `git checkout <branch>` / `git switch`                                        | ❌ blocked                                                    | ❌ blocked                             | ❌ blocked                          | Branch switching loses workspace; not how agents change branches.                                                                                                                                                                                                                                                                                                                         |
| `git stash*`                                                                  | ❌ blocked (absolute, no role override)                       | ❌ blocked                             | ❌ blocked                          | Stash captures every dirty file in the worktree it runs in — no pathspec granularity. In a multi-agent repo, a stash lifts other agents' WIP; the pop either silently re-stages foreign content or conflicts with no clean recovery. The integrator's recovery when repo-root sync finds dirty files is to halt and surface to the human (per the integration procedure), never to stash. |
| `git clean`                                                                   | ❌ blocked                                                    | ❌ blocked                             | ❌ blocked                          | Deletes untracked files; rarely the right answer for agents.                                                                                                                                                                                                                                                                                                                              |
| `git revert <commit>`                                                         | ⚠️ `--confirmed` required                                     | ⚠️ `--confirmed` required              | ⚠️ `--confirmed` required           | Multi-agent commits often span scopes; inspection precedes revert.                                                                                                                                                                                                                                                                                                                        |
| `git merge`/`rebase`/`cherry-pick` on main                                    | ❌ unless integrator role or `TELECLAUDE_OVERRIDE_APPROVED=1` | ✅ allowed                             | (n/a)                               | Replays produce commits via paths that bypass `telec code commit`'s Path A/B/C gate.                                                                                                                                                                                                                                                                                                      |
| `git push origin main`                                                        | ❌ blocked                                                    | ✅ allowed (from integration worktree) | (n/a)                               | Only the integrator publishes to canonical main.                                                                                                                                                                                                                                                                                                                                          |

**Legend.** ✅ = allowed; ❌ = wrapper blocks with diagnostic; ⚠️ = blocked
without the `--confirmed` flag, allowed with it. `--confirmed` is a
deliberate friction: the wrapper requires the agent to re-run the
exact command with `--confirmed` appended after reading the printed
inspection checklist.

**The integration-worktree extras** matter because the worktree's index
and working tree are owned by the state machine's
`DELIVERY_BOOKKEEPING` step, which commits whatever is staged with no
path filter. Any mutation introduced from outside the state machine can
produce a delivery-reverting commit on origin/main. `--confirmed` is
the integrator's deliberate ratification that the inspection has
happened.

**Notes carried over from earlier prose:** `rebase.autoStash` and
`merge.autoStash` are forced off on every wrapper-driven git call.
`git add -A`/`git add --all`/`git add .` are blocked on main for
non-integrators regardless of the table above — staging on main always
names files explicitly.

## Inputs / Outputs

Sealed contract — exactly:

- `"<message>"` — one quoted commit message (required when `--approved`).
- `--approved` — human-approved gate; absence triggers Path A/B/C guidance.
- `--include <path> [<path> ...]` — declare files outside the resolved
  workspace scope that must be in this commit (e.g., a file the human
  collaboratively edited that the scope heuristic missed). Each declared
  path must contribute a change; clean paths are rejected.

Nothing is forwarded to git: no `-m`, no `-F`, no `--`, no bare pathspecs.
The pathspec commit is built internally from `workspace scope plus
--include paths`.

**Outputs:** committed changeset, or failure with actionable diagnostics.

## Invariants

1. **Lock serialisation.** `main_branch_lock()` (flock on
   `GIT_MAIN_LOCK_PATH`) serialises the entire `_commit_under_lock` body.
   No two agents can be inside their commit phase at the same time. The
   lock auto-releases on process exit or crash.

   Stale `.git/index.lock` self-heal: immediately after acquiring the
   flock, `_commit_under_lock` calls `wait_for_index_lock_clear()`. Two
   removal paths: `lsof` shows no process holding the lock AND mtime
   ≥ 10s (orphan signature, fast path), or mtime ≥ 180s (hung-holder
   ceiling, slow path). Polls every 5s with structured logs at every
   state. Self-healing without ever discarding an active git process's
   work. The Python flock does not prevent orphan `index.lock` —
   different lock, different file, owned by git itself — so this check
   is the only protection against a previous git process that was
   killed mid-write.

2. **Workspace scope is authoritative — for pathspec construction, not staging.**
   `resolve_workspace_scope_resolution()` is the single owner of
   worktree-vs-shared-branch scope. The scope set drives the commit's
   pathspec (with `--include` adding explicit, agent-declared paths and
   untracked-not-staged files dropped); it does **not** drive staging.
   Staging is a narrow follow-up step that runs only on the three cases
   git's data model genuinely requires it for: untracked files in the
   pathspec, unmerged-index files in the pathspec, and partial-staged
   tracked files (handled via `telec code add` recovery). Modified-tracked
   files in the pathspec are committed straight from the working tree —
   `git commit -- <path>` records the working-tree version.

3. **Pathspec on commit IS the boundary.** The final `git commit` runs with an
   explicit pathspec equal to `workspace scope plus --include paths` (minus
   untracked-not-staged scope files). Anything else in the index — concurrent
   stage from another session, crash residue from a prior failed commit,
   human-staged files outside the agent's scope — is **invisible to the
   pathspec** and stays staged for its owner. There is no separate
   "foreign-staged" check; the pathspec alone enforces the boundary. Agents
   must not unstage foreign files they see in the index.

<!-- planned:telec-code-delegates-to-make -->
4. **Format + lint run in-process before `git commit --no-verify`.** `quality_paths`
   is the pathspec filtered to existing files; format runs first (so lint
   checks post-format bytes); lint runs second; deletion-only commits skip both.
   No framework stash, no working-tree reset outside the pathspec. See ADR-0036.
<!-- /planned:telec-code-delegates-to-make -->
<!-- superseded: "Pre-commit hook owns format + lint." invariant -->

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
telec code commit --approved "feat(scope): subject"
  → ABC gate satisfied (--approved present)
  → lock acquired
  → wait_for_index_lock_clear (self-heal any stale .git/index.lock)
  → workspace scope = WORKTREE → all dirty paths
  → pathspec = scope (no includes)
  → drop untracked-new files from pathspec (require explicit declaration)
  → stage ONLY untracked-or-unmerged files that are in pathspec
    (modified-tracked files are NOT staged — they ride the pathspec)
  → partial-staging guard: block if any pathspec file has both staged
    and unstaged changes
  → real git commit -F <msg> -- <pathspec>
  → format + lint run in-process before --no-verify commit <!-- planned:telec-code-delegates-to-make -->
  → lock released
```

### Agent commit on main (Path A — non-functional)

```
telec code commit --approved "chore(docs): update snippets [skip ci]"
  → ABC gate satisfied (--approved + [skip ci])
  → lock acquired
  → workspace scope = SHARED_BRANCH → scoped dirty paths
  → pathspec = scope minus untracked-not-staged
  → modified-tracked docs ride the pathspec unstaged
  → real git commit -F <msg> -- <pathspec>
  → format + lint run in-process before --no-verify commit <!-- planned:telec-code-delegates-to-make -->
  → lock released
```

### Agent commit with declared extras (scope heuristic missed a file)

```
telec code commit --approved "fix(scope): subject" --include path/to/extra.py
  → ABC gate satisfied
  → lock acquired
  → workspace scope = SHARED_BRANCH → scoped dirty paths
  → pathspec = scope ∪ {path/to/extra.py}
  → stage extra.py only if it's untracked or unmerged
  → assert extra.py contributes a change (else error)
  → partial-staging guard runs against the merged pathspec
  → real git commit -F <msg> -- <pathspec>
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

**Empty pathspec.** `workspace scope plus --include = ∅`. The agent has
edited nothing in scope and declared no includes. Exit code 1 with guidance
pointing at `telec code changed` and the `--include <path>` recipe. There is
no silent fallback that commits the pre-staged index — committing what the
agent did not declare is precisely what the pathspec boundary prevents.

**Declared `--include` path is clean.** The agent named a file with no
changes. Exit code 2 — the agent's declaration must match reality; we don't
quietly drop unreachable claims.

<!-- planned:telec-code-delegates-to-make -->
**In-process gate failure.** Format or lint fails before `git commit --no-verify`
is invoked. The lock is released (Python `with` guarantees `__exit__` even on
`SystemExit`). Files are unchanged — the commit did not happen. The agent fixes
the violation and retries `telec code commit --approved`.
<!-- /planned:telec-code-delegates-to-make -->
<!-- superseded: "Pre-commit hook failure." failure mode -->

**Path B/C gate.** Functional files on main without human approval. Exit
with guidance. Path B: human approves with `--approved`. Path C: human
approves the commit; the agent dispatches `/next-review-commits` only when
the patch series has no reviewer yet. Follow-up commits for that patch series
are sent to the same reviewer.

## See also

- docs/global/software-development/design/workspace-scoping.md
- docs/global/software-development/policy/version-control-safety.md
