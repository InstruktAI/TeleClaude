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
  on `integrator-main-clearance` (see **REPO ROOT SYNC REQUIRED** below). The one exception:
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

<!-- planned-change:integrator-repo-root-sync-classification -->

Repo-root `main` has diverged from origin/main after a delivery push (the `--ff-only`
pull could not fast-forward). Two cases:

<!-- change:integrator-repo-root-sync-classification -->

After a delivery push, repo-root `main` is both ahead of and behind origin/main. That is
the expected condition in a repository where agents commit doc and artifact work directly
on `main`, not a failure — the state machine reports it classified rather than as an
error, and carries the intersection of the incoming file list with the repo-root dirty set
so you can see which case you are in before you act. The merge is yours to run and yours
to own; the state machine never performs it. Divergence has two instruction shapes:

<!-- /planned-change:integrator-repo-root-sync-classification -->

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
  escalate on first contact — **keep `integrator-main-clearance` live**:
  1. Set the prescribed recurring reminder at the existing ~2–3 minute caller
     interval. Do not use a local sleep, cron, `/loop`, or conversational message
     as its timer.
  2. When it fires, re-check repo-root cleanliness (`git -C <root> status --short`).
     Still dirty → leave the recurring reminder live and wait again. Clean →
     cancel it, resume `telec todo integrate`, and continue the drain.
<!-- planned-change:telec-code-dirty-path-owners -->
  3. Escalate to the human only after the block persists ~15–20 min (≈5 beats) of
     continuous dirtiness — past that window it is no longer transient WIP but a
     stuck or abandoned change that needs a human.
<!-- change:telec-code-dirty-path-owners -->
  3. After the block persists ~15–20 min (≈5 beats) with the same complete path
     set, continue into **After the dirty-main quiet window** below. Human
     escalation is reserved for intent that remains genuinely ambiguous after
     ownership resolution and integrator inspection, or for a protection
     condition that survives the bound below.
<!-- /planned-change:telec-code-dirty-path-owners -->

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
  worker's and stay in the `integrator-main-clearance` flow above.

  While waiting you are not idle: you hold the lease and the in-flight candidate is
  already committed, ready to push the instant main clears.

<!-- planned:integrator-repo-root-sync-classification -->
- **Git operation failure:** Fetch, repository-state inspection, fast-forward, and
  bookkeeping-push failures render a distinct **INTEGRATION ERROR** outcome rather than
  a divergence instruction. The integrator stays active, executes the emitted recovery
  steps within its governance, and re-enters `telec todo integrate`; the failure never
  parks the integrator merely because the failed operation was implied by its task.
<!-- /planned:integrator-repo-root-sync-classification -->

<!-- planned:telec-code-dirty-path-owners -->
#### After the dirty-main quiet window

When the same complete blocking path set remains dirty for the full quiet window, run

```
telec code owners <path>...
```

with every blocking path from the integration instruction on each post-window reminder
beat while the set remains dirty. The command performs no age calculation. Each invocation
takes one fresh snapshot of open local-project sessions and returns a JSON object keyed by
every requested project-relative path.

Resolve ownership on every post-window reminder beat while the complete blocking path set
remains dirty, using a fresh query invocation and therefore a fresh open-session snapshot.
Coordination remains once per owner per distinct complete blocking set: never contact an
already-coordinated owner again for that set. If re-resolution exposes a different live
owner that has not yet been coordinated for the set, send that owner one grouped message.
If a previously owned path now reports null, the former custodian is no longer live and the
path enters the null-custody rules below. Hold without mutation or human escalation only
while the latest result still reports a live custodian or a positive
`undetermined_session_count`; keep the reminder active so either condition can clear. If
the same blocking condition — an unchanged live owner-path group or a positive
undetermined count — survives three consecutive later reminder beats after it is first
observed, escalate once for the complete blocking set. Name every still-live owner group
and its paths plus the undetermined count, never the identities behind that count. Do not
message an owner a second time. The integrator then remains alive as the single
human-blocker beacon without mutating the protected paths or emitting another escalation
for that set, and the reminder continues fresh read-only observation so ordinary session
completion can still resume the queue.

Group owned paths by the reported TeleClaude session UUID. Send each live owner one
coordination message naming its complete blocking-file group and asking it to commit or
otherwise settle that work. Do not split one owner's group into per-file messages, rescan
closed sessions, inspect commit authorship, or recheck liveness after the ownership
snapshot.

A null owner transfers custodianship to the integrator. Inspect the path's diff and
surrounding intent, then commit discernible intentional work as-is or revert abandoned
residue through the sanctioned path-scoped surface. Null ownership is never permission to
discard blindly. Escalate only when the path's intent remains genuinely ambiguous after
inspection.

If the latest query reports a positive `undetermined_session_count`, a null owner transfers
inspection custodianship but not destructive authority. Preserve discernible intentional
work in a commit when safe, but do not classify or revert residue as abandoned on that
result and do not escalate solely because attribution is temporarily undetermined. Wait
for the next reminder beat and re-resolve. Revert authority returns only when a later fresh
result reports zero undetermined sessions and no live owner for the path. Escalate only
intent that remains genuinely ambiguous after a result has established that custody. A
positive count that persists through the shared three-beat bound follows the one
protection-condition escalation above; that escalation reports the unresolved safety
brake and makes no claim about path intent.
<!-- /planned:telec-code-dirty-path-owners -->

#### Reminder: integrator-main-clearance

- **Owner:** Integration procedure.
- **Parameters:** none; project root and integrator session derive from the
  authenticated caller and current integration checkpoint.
- **Activation anchor:** immediately when repo-root main blocks synchronization.
- **Duration:** the existing ~2–3 minute interval owned by this procedure.
- **Recurrence:** recurring while repo-root main remains blocked.
- **Arm condition:** set on first dirty-main block before yielding.
<!-- planned-change:telec-code-dirty-path-owners -->
- **Intent:** `Recheck whether repo-root main is clear without touching another session's work. If clear, resume integration; otherwise continue the prescribed wait and escalation discipline.`
<!-- change:telec-code-dirty-path-owners -->
- **Intent:** `Recheck whether repo-root main is clear without touching another session's work. If clear, resume integration; otherwise continue the prescribed wait and post-window ownership discipline.`
<!-- /planned-change:telec-code-dirty-path-owners -->
- **Firing behavior:** inspect current repo-root cleanliness and follow
  **REPO ROOT SYNC REQUIRED** without treating the reminder as ownership of the
  dirty paths. After the quiet window, re-run the read-only ownership query for
  an unchanged dirty set, but never re-contact an owner already coordinated for
  that set.
- **Cancellation:** cancel when main clears, the integration session reaches a
  terminal outcome, or the human explicitly supersedes the wait. A coordinated
  live owner or positive undetermined count keeps the reminder live for fresh
  read-only re-resolution before and after the single bounded escalation,
  without triggering repeat contact or escalation.
- **Invocation:** `telec reminders set integrator-main-clearance`.

#### Reminder: integrator-candidate-settledness

- **Owner:** Integration procedure and its state-machine formatter.
- **Parameters:** none; the queue and checkpoint derive from the authenticated
  integrator session.
- **Activation anchor:** immediately when the integration caller emits its
  candidate-settledness wait.
- **Duration:** the interval emitted by that caller. This declaration neither
  duplicates nor changes the caller-owned timer.
- **Recurrence:** one-shot.
- **Arm condition:** set before yielding for the caller's settledness window.
- **Intent:** `Recheck the integration queue after its caller-owned settledness interval. If a candidate is ready, continue the drain; otherwise follow the integration procedure's queue-empty outcome.`
- **Firing behavior:** invoke the integration state machine once and execute its
  returned instruction verbatim.
- **Cancellation:** cancel when a material candidate signal causes earlier
  re-entry or the integration state machine reaches a terminal outcome.
- **Invocation:** `telec reminders set integrator-candidate-settledness`.

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

Park after bookkeeping completes. Hold the prescribed recurring long-interval
reminders while awaiting the next candidates, and end only when directed.

### When to end, when to wait, when to beacon

The integrator's terminal behavior has three shapes — do not collapse them:

- **Queue drained (INTEGRATION COMPLETE):** park on the prescribed recurring
  long-interval reminders and await the next candidates. The integrator is a
  singleton and is not re-dispatched; end only when directed.
- **Transient block (dirty main):** do not end and do not idle — keep
  `integrator-main-clearance` live
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
