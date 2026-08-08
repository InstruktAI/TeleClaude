---
description: 'Integration phase. Drive the integration state machine, handle squash commits, conflicts, push rejections, and lease contention.'
visibility: 'public'
---

# Integration — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md

## Goal

Merge candidate branches to canonical main via the integration state machine, handling
each decision point until the queue is drained.

## Preconditions

- Candidate branches exist in the FIFO queue.
- No other integrator session holds the lease.
- The integrator operates in a persistent worktree at `trees/_integration/` (detached HEAD
  from `origin/main`), created on first run and reused across subsequent runs. Reset to
  `origin/main` before each merge. Repo root cleanliness is irrelevant — dirty files, hot
  patches, and operational edits on `main` do not affect integration.
- Worker worktrees branch from `origin/main` (not local HEAD).
- **The agent's cwd is the integration worktree.** All git and make commands run from
  there without `-C` prefixes. Commands targeting project root (repo sync) are emitted
  by the engine with explicit `-C <project_root>` paths. **The worktree's index and
  working tree belong to the state machine.** Only `telec todo integrate` and the
  `telec code commit` instructions it emits write to them. Read-only git commands —
  `status`, `log`, `show`, `diff <ref>..<ref>`, `rev-parse` — are fine. Mutating
  commands inside the worktree are gated per the wrapper matrix (see
  `docs/project/design/code-commit.md`): `stash` is absolutely blocked everywhere
  (no role carve-out — stash is too coarse for a multi-agent repo); `checkout <ref>
-- <path>`, `restore <path>`, and `restore --source <ref> <path>` require the
  `--confirmed` flag after reading the printed inspection checklist; pathspec
  `reset HEAD <path>` / `restore --staged <path>` are index-only and allowed
  without ceremony. The `--confirmed` friction is the integrator's deliberate
  ratification that the working-tree mutation has been inspected and will not
  silently overwrite intentional state before the next bookkeeping commit.
- **When repo-root sync is blocked by dirty files**, the integrator does NOT stash
  and does NOT rebase across foreign WIP — dirty files in the project root belong to
  concurrent agents, and only their author may resolve them. But this block is almost
  always **transient**: those agents commit their snippets within minutes and main
  goes green on its own. So do not idle and do not escalate on first contact — wait
  and retry on a heartbeat (see **REPO ROOT SYNC REQUIRED** below). The one exception:
  a trivial repo-hygiene/config file (`.gitignore` and the like) may be committed
  as-is to unblock — a non-destructive move detailed under **REPO ROOT SYNC
  REQUIRED**. The state machine emits this guidance when it observes the divergence.

## Steps

1. Call `telec todo integrate [slug]` to enter the state machine.
2. Read the returned instruction block and execute it verbatim.
3. After executing, call `telec todo integrate` again to advance.
4. Repeat until a terminal instruction is returned (COMPLETE or LEASE_BUSY).
5. Before any push, run repo-wide verification:
   - `telec code lint --all`
   - `telec code test --all`
     If either command fails, fix the failures, rerun both, then resume the state machine.
     Use the `telec code` verbs, not raw `make`: `telec code lint --all` runs the native
     `make lint` leg **and** the TeleClaude guardrails lane (raw `make lint` skips the
     guardrails), matching exactly what the pre-push hook enforces.
   - The pre-push hook enforces `telec code lint --all` automatically. If the hook blocks
     the push with `ERROR: Integration push blocked — telec code lint --all failed.`,
     resolve the reported lint violations and retry.
   - The canonical source is `templates/quality/githooks/pre-push` — edit this to change
     behavior. The tracked `.githooks/pre-push` is a compatibility entrypoint that resolves
     the repository root and execs the canonical source; it carries no behavior of its own,
     so it needs no syncing and neither does any per-worktree copy of it. The active
     `.git/hooks/pre-push` that git executes is deployed from the canonical source. The CI
     `make lint` check is a redundant post-push catch layer; the pre-push guard is the
     primary enforcement surface.

The state machine returns one of the following instruction blocks at each step.

### SQUASH COMMIT REQUIRED

The branch has been squash-merged; staged changes are ready.

1. Read the context: diff stats, branch commit history, `prd`, optional
   `architecture` when present, and `implementation-plan`.
2. Compose a commit message capturing the full delivery intent:
   - Subject: imperative, scoped — e.g. `feat(my-feature): deliver my-feature`
   - Body: summarize what changed, key decisions, scope
   - Footer: none. Attribution and provenance are stamped by the sealed commit
     surface, not composed here; `software-development/policy/commits` is the
     canonical source and this procedure does not restate it.
3. Run `telec code commit --approved '<message>'`, then call `telec todo integrate`.
4. When the state machine reaches push, `telec code lint --all` and `telec code test --all` must already be green.

### CONFLICT RESOLUTION REQUIRED

The squash merge encountered conflicts.

**Cardinal rule: preserve the best of both worlds.** Conflicts mean two branches
independently evolved the same files. Neither side is "the winner." Both contain
intentional work that must survive. Picking one side wholesale destroys the other's
contributions — this is the #1 cause of silent regression in multi-agent workflows.

**Resolution procedure:**

1. Read each conflicted file; understand the **intent** on both sides.
   - What feature, fix, or architectural change does each side introduce?
   - Are the changes orthogonal (touching different concerns in the same file) or
     genuinely contradictory (mutually exclusive designs for the same concern)?
2. For **orthogonal changes** (the common case): merge both. If side A adds a new method
   and side B refactors an existing one, the resolved file contains both the new method
   and the refactored code.
3. For **architectural conflicts** (rare): identify which design is more evolved, then
   carry forward the features and fixes from the other side into that design. Example:
   if side A introduced subprocess isolation and side B added playlist controls, the
   resolution uses the subprocess architecture with the playlist features integrated.
4. **Never resolve by choosing one side entirely.** Picking "ours" or "theirs" wholesale for a file is almost certainly wrong — the merge must integrate both sides' meaningful changes. The only exception is when one side made no meaningful changes to the file (e.g., a whitespace-only diff).
5. After resolving, verify the merged file is functionally complete:
   - Does it preserve all public API surface from both sides?
   - Does it preserve all behavioral features (not just code) from both sides?
   - Are tests from both sides still valid against the merged implementation?
6. Declare resolved files via `telec code add <files>`. The sealed equivalent
   of `git add` for unmerged-index recovery — `git add` itself is blocked for
   agents per the wrapper matrix. NEW (untracked) resolution files (e.g. a
   file added on one side that the other side deleted) also go through this
   command; modified-tracked resolutions ride the pathspec via `telec code
commit` directly.
7. Compose a commit message (same quality standard as squash commit). In the body,
   note which conflicts were resolved and how both sides' contributions were preserved.
8. Run `telec code commit --approved '<message>'`, then call `telec todo integrate`.
9. If conflicts are genuinely unresolvable, call `telec todo integrate` without
   committing — the state machine will detect this and re-prompt.
10. Before any push, `telec code lint --all` and `telec code test --all` must pass.

### PUSH REJECTION RECOVERY

Push to origin/main was rejected (likely non-fast-forward).

1. Diagnose: `git fetch origin && git log --oneline origin/main ^HEAD`.
2. Rebase: `git rebase origin/main`.
3. Resolve any new conflicts, then `git push origin HEAD:main`.
4. Call `telec todo integrate`.

### REPO ROOT SYNC REQUIRED

<!-- planned-change:integrator-delivery-path-silent-defects -->

Repo-root `main` has diverged from origin/main after a delivery push (the `--ff-only`
pull could not fast-forward). Two cases:

<!-- change:integrator-delivery-path-silent-defects -->

After a delivery push, repo-root `main` is both ahead of and behind origin/main. That is
the expected condition in a repository where agents commit doc and artifact work directly
on `main`, not a failure — the state machine reports it classified rather than as an
error, and carries the intersection of the incoming file list with the repo-root dirty set
so you can see which case you are in before you act. The merge is yours to run and yours
to own; the state machine never performs it. Two cases:

<!-- /planned-change:integrator-delivery-path-silent-defects -->

- **Clean working tree:** merge origin/main into local main, resolving any conflicts per
  the **CONFLICT RESOLUTION REQUIRED** section above, then call `telec todo integrate`.
  Never rebase repo-root `main`: it is shared, and a clean tree does not make the
  divergence yours — the commits that produced it are concurrent sessions' committed
  work, referenced elsewhere by SHA. If the merge cannot be resolved, STOP and ask the
  human.
- **Blocked on dirty main:** concurrent agents have uncommitted work in the project
  root. The integrator must never stash, overwrite, or rebase across it — only the
  authoring agent may resolve it. This block is **transient**: those agents commit
  within minutes and main clears. So do not idle, do not end the session, and do not
  escalate on first contact — **retry on a heartbeat**:
  1. Set a non-blocking heartbeat (~2–3 min): a one-shot
     `Bash(run_in_background=true)` `sleep` — never cron or `/loop` (those leave
     zombie timers).
  2. When it fires, re-check repo-root cleanliness (`git -C <root> status --short`).
     Still dirty → reset the heartbeat and wait again. Clean → resume
     `telec todo integrate` and continue the drain.
  3. Escalate to the human only after the block persists ~15–20 min (≈5 beats) of
     continuous dirtiness — past that window it is no longer transient WIP but a
     stuck or abandoned change that needs a human.

  **Trivial repo-hygiene files are a sanctioned exception to the wait.** When the
  only dirty paths are repo-hygiene or config files — `.gitignore`, `.gitattributes`,
  editor/tooling config, and the like — whose diff is small and self-evidently benign
  on inspection, commit them as-is to unblock the sync rather than waiting out the
  window. Committing-as-is is **non-destructive**: it preserves the change exactly,
  which is what makes it safe — unlike stash, overwrite, discard, or rebase-across,
  which relocate or destroy a worker's change and stay forbidden for every dirty path.
  Inspect the diff first, then land it with a pathspec-scoped
  `telec code commit --approved --include <path>` under an honest message, and rebase.
  The exception is narrow on purpose: source, tests, docs-with-content, lockfiles, and
  delivery-tied generated artifacts are a worker's substantive deliverable — never
  commit those, and when you cannot tell which kind a dirty file is, treat it as a
  worker's and stay in the heartbeat-retry flow above.

  While waiting you are not idle: you hold the lease and the in-flight candidate is
  already committed, ready to push the instant main clears.

### LEASE_BUSY

Another integrator session already holds the lease. Exit immediately.
Do not attempt to break the lease.

### ALREADY INTEGRATED (silent skip)

The state machine detected that the candidate's content is already on main —
either via git ancestry (regular merge) or via empty squash diff (squash merge
that produced no staged changes). The candidate is silently advanced to
`CANDIDATE_DELIVERED` and the next candidate is processed. No agent action needed.

This happens when a candidate is re-dequeued after a daemon restart or stale
re-queue. The agent sees no instruction for this candidate; the state machine
logs `integration.candidate.already_merged` and moves on.

### INTEGRATION COMPLETE

All candidates have been processed. The state machine automatically pushes any
accumulated repo root bookkeeping commits (orchestrator dumps, `[skip ci]`
housekeeping) to origin/main after syncing local main via pull. If the pull
failed and the agent resolved it manually, push repo root using the explicit
project root path emitted by the engine.

Depart per the Heartbeat policy — your `telec sessions end self` is a departure, not an inline command.

### When to end, when to wait, when to beacon

The integrator's terminal behavior has three shapes — do not collapse them:

- **Queue drained (INTEGRATION COMPLETE):** end the session — `telec sessions end
self`. The runner re-dispatches a fresh integrator when candidates next queue.
  Dying clean is correct here; do not linger.
- **Transient block (dirty main):** do not end and do not idle — heartbeat-retry
  until main clears, then continue the drain (see **REPO ROOT SYNC REQUIRED**). The
  block self-heals as concurrent agents commit.
- **Unrecoverable block (genuine human decision):** stay alive as a beacon, but only
  after recovery and the retry window are exhausted, so the human sees and intervenes.

## Outputs

- Merged candidates on canonical main (pushed from integration worktree).
- Repo root bookkeeping pushed to origin/main (automatic after successful pull sync).
- Cleaned worktrees and branches.
- `integration.*` lifecycle events at each state transition.

## Recovery

The state machine checkpoint is crash-safe. If the integrator process dies at any
point, re-calling `telec todo integrate` reads the durable checkpoint and resumes
from the last persisted phase. No manual checkpoint editing is required.

### Agent-actionable recovery

- **Squash commit fails:** Read the error and retry the commit.
- **Conflicts unresolvable:** Call `telec todo integrate` without committing — the state
  machine detects no HEAD advancement and re-prompts.
- **Push repeatedly rejected:** Fetch, rebase, resolve, push, then call
  `telec todo integrate`. If the problem persists, check for concurrent integrators.

### Automatic crash recovery

| Crash point                       | What happens on re-entry                                             |
| --------------------------------- | -------------------------------------------------------------------- |
| After dequeue, before merge       | Resumes at merge. No work lost.                                      |
| After merge, before agent commits | Re-prompts for commit. Git index (staged changes) persists on disk.  |
| After commit, before push         | Pushes squash commit from integration worktree.                      |
| After push rejection              | Re-checks if integration worktree HEAD matches remote main.          |
| During cleanup                    | Re-runs cleanup (idempotent). Missing worktrees/branches are no-ops. |
| After candidate delivered         | Marks integrated, resets to IDLE, loops for next candidate.          |

Useful commands during recovery:

- `telec todo artifacts list <slug>`
- `telec todo show <slug>`
