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
- Worker worktrees branch from `origin/main` (not local HEAD), and `origin/main` is the
  only baseline a slug worktree references: an agent inside `trees/<slug>` does not name
  the local `main` branch in any git invocation — `main`, `heads/main`, `refs/heads/main`,
  or a range with one of those as an endpoint — for any subcommand, read-only ones
  included. The rule keeps a candidate's ancestry and working tree free of work that sits
  on local `main` but not yet on `origin/main`.
- The git wrapper refuses a local-`main` reference inside a slug worktree with no
  override; the wrapper matrix in `docs/project/design/code-commit.md` carries the rule.
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
<!-- planned-change:integrator-stranded-dirt-by-asking -->
- **When repo-root sync is blocked by dirty files**, the integrator does NOT stash
  and does NOT rebase across foreign WIP — dirty files in the project root belong to
  concurrent agents, and only their author may resolve them. But this block is almost
  always **transient**: those agents commit their snippets within minutes and main
  goes green on its own. So do not idle and do not escalate on first contact — wait
  on `integrator-main-clearance` (see **REPO ROOT SYNC REQUIRED** below). The one exception:
  a trivial repo-hygiene/config file (`.gitignore` and the like) may be committed
  as-is to unblock — a non-destructive move detailed under **REPO ROOT SYNC
  REQUIRED**. The state machine emits this guidance when it observes the divergence.
<!-- change:integrator-stranded-dirt-by-asking -->
- **When repo-root sync is blocked by dirty files**, the integrator never stashes,
  overwrites, rebases across, or discards them. It waits on `integrator-main-clearance`
  and resolves each dirty path on its own: it asks the sessions that can have written
  the path, and commits the path as-is once it is quiet and unclaimed (see **REPO ROOT
  SYNC REQUIRED** below). The state machine emits this guidance when it observes the
  divergence.
<!-- /planned-change:integrator-stranded-dirt-by-asking -->

## Steps

1. Call `telec todo integrate [slug]` to enter the state machine.
2. Read the returned instruction block and execute it verbatim.
3. After executing, call `telec todo integrate` again to advance.
3a. After a canonical-main advancement, inspect the maintenance actions recorded
    for that activation. Treat pending actions as pending, judge terminal
    failures and recover within the integration lane, and keep outstanding
    live-runtime judgment with the integrator. Continue observing those actions
    on the parked queue watch when they outlive this drain.
    `telec code maintenance status` reports the checkout's outstanding actions,
    terminal failures, and integrator judgment, each with its recovery command.
    After the cause of a terminal failure is addressed, `telec code maintenance
    retry` replays that action for its original activation; `telec code
    maintenance drain` resumes interrupted work and records maintenance
    readiness when no owed action remains.
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
     surface, not composed here; `sdlc/policy/commits` is the
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

After a delivery push, repo-root `main` is both ahead of and behind origin/main. That is
the expected condition in a repository where agents commit doc and artifact work directly
on `main`, not a failure — the state machine reports it classified rather than as an
error, and carries the intersection of the incoming file list with the repo-root dirty set
so you can see which case you are in before you act. The merge is yours to run and yours
to own; the state machine never performs it. Divergence has two instruction shapes:

- **Clean working tree:** merge origin/main into local main, resolving any conflicts per
  the **CONFLICT RESOLUTION REQUIRED** section above, then call `telec todo integrate`.
  Never rebase repo-root `main`: it is shared, and a clean tree does not make the
  divergence yours — the commits that produced it are concurrent sessions' committed
  work, referenced elsewhere by SHA. If the merge cannot be resolved, STOP and ask the
  human.
<!-- planned-change:integrator-stranded-dirt-by-asking -->
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
  3. After the block persists ~15–20 min (≈5 beats) with the same complete path
     set, continue into **After the dirty-main quiet window** below. Human
     escalation is reserved for intent that remains genuinely ambiguous after
     ownership resolution and integrator inspection, or for a protection
     condition that survives the bound below.

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
<!-- change:integrator-stranded-dirt-by-asking -->
- **Blocked on dirty main:** paths other sessions have not committed block the sync.
  The integrator never stashes, overwrites, rebases across, or discards them.
  Committing a path as-is is the only change it makes to another session's work,
  because a commit preserves the work exactly and a revert undoes it
  (`general/principle/trust-and-guardrails`). Do not idle and do not end the
  session — **keep `integrator-main-clearance` live**:
  1. Set the prescribed recurring reminder. Do not use a local sleep, cron, `/loop`,
     or conversational message as its timer.
  2. When it fires, re-enter `telec todo integrate`, which re-runs repo-root
     synchronization. No longer blocked → cancel the reminder and continue the drain.
     Still blocked → the returned decision identifies the dirty paths that block
     synchronization: the listed dirty overlap when repo-root `main` is only behind,
     and every path `git -C <root> status --short` reports when its history is split.
     Resolve each blocking path under **Resolving a dirty path** below, keep the
     reminder live, and wait again. A dirty path the decision does not identify as
     blocking is left alone.

  **Trivial repo-hygiene files are committed on sight.** A dirty repo-hygiene or
  config file — `.gitignore`, `.gitattributes`, editor/tooling config, and the like —
  whose diff is small and self-evidently benign on inspection is committed as-is on
  first sight instead of going through per-path resolution. Inspect the diff first,
  then land it with a pathspec-scoped `telec code commit --approved --include <path>`
  under an honest message.

  While waiting you are not idle: you hold the lease and the in-flight candidate is
  already committed, ready to push the instant main clears.
<!-- /planned-change:integrator-stranded-dirt-by-asking -->

- **Git operation failure:** Fetch, repository-state inspection, fast-forward, and
  bookkeeping-push failures render a distinct **INTEGRATION ERROR** outcome rather than
  a divergence instruction. The integrator stays active, executes the emitted recovery
  steps within its governance, and re-enters `telec todo integrate`; the failure never
  parks the integrator merely because the failed operation was implied by its task.

<!-- planned-change:integrator-stranded-dirt-by-asking -->
#### After the dirty-main quiet window

Keep waiting. Dirty paths on repo-root main belong to the sessions that declared them
and those sessions commit them; the integrator queries no ownership, contacts no
session, and mutates no path it did not deliver. `integrator-main-clearance` stays live
and re-checks cleanliness on each beat.

When the same complete blocking path set survives three consecutive reminder beats after
it is first observed, escalate once for that set, cancel the reminder, and hold as the
single human-blocker beacon without mutating the protected paths or emitting another
escalation for that set. The next move belongs to the human.

#### Reminder: integrator-main-clearance

- **Owner:** Integration procedure.
- **Parameters:** none; project root and integrator session derive from the
  authenticated caller and current integration checkpoint.
- **Activation anchor:** immediately when repo-root main blocks synchronization.
- **Duration:** the existing ~2–3 minute interval owned by this procedure.
- **Recurrence:** recurring while repo-root main remains blocked.
- **Arm condition:** set on first dirty-main block before yielding.
- **Intent:** `Recheck whether repo-root main is clear without touching another session's work. If clear, resume integration. Otherwise keep waiting and keep this reminder; on escalating to a human, cancel it and hold as a beacon — the next move is theirs.`
- **Firing behavior:** inspect current repo-root cleanliness and follow
  **REPO ROOT SYNC REQUIRED** without treating the reminder as ownership of the
  dirty paths, and without querying or contacting any other session.
- **Cancellation:** cancel when main clears, the integration session reaches a
  terminal outcome, or the human explicitly supersedes the wait. Cancel it at
  the single bounded escalation that transfers the next move to the human.
- **Invocation:** `telec reminders set integrator-main-clearance`.
<!-- change:integrator-stranded-dirt-by-asking -->
#### Resolving a dirty path

On each `integrator-main-clearance` beat, take each dirty path on its own. Each path
keeps its own history of what was sent and claimed; a set of paths is never treated as
one unit.

1. **Recently written.** A path last modified within the current reminder interval is
   being worked on. Leave it for a later beat.
2. **Named by a pending-doc marker.** When the path's uncommitted diff adds a pending
   marker naming a todo slug — a `planned:<slug>` or `planned-change:<slug>` block, a
   `<stem>.<slug>.md` companion, or a `delivered_by` entry — that todo's prepare
   orchestrator wrote it. Find that session from the todo's state
   (`telec todo show <slug>`). If it is live, send it the path under step 3's message.
   If it is gone, read its transcript (`telec history show <session-id>`) together
   with the todo's state and resolve the path from that evidence under step 5.
3. **Ask once.** Every other quiet path is put, once, to the live sessions of this
   project on this computer that can write files on main: orchestrators whose job is
   `prepare-orchestrator`, `intaker`, `architect`, or `planner`, and sessions carrying
   no system role (`telec sessions list --all`). Each recipient receives one message
   listing the paths:
   `These paths are dirty on main and block integration: <paths>. If you were in the middle of work, arm halt-to-respond first. Then: for each path that is yours, commit it now if it is ready and released for commit, otherwise reply that you are still working on it; if none are yours, end your turn with NOOP.`
4. **Claimed.** A recipient that replies that a path is its own and still in progress
   owns that path. Keep waiting for its commit.
5. **Quiet and unclaimed on a later beat.** A path still dirty, not recently written,
   and claimed by no one after its message was sent is committed as-is with a
   pathspec-scoped `telec code commit --approved --include <path>` under a message
   that names it as stranded work. The one exception is a path whose pending-doc
   markers name a todo that is removed or delivered while its prepare orchestrator's
   transcript shows the work was abandoned: revert that path instead.
6. **Escalate** to the human, once per path, only when a claimed path stays
   uncommitted for three consecutive beats after its claim, or when a path's diff is
   unintelligible. Leave an escalated path untouched and hold as its blocker beacon.

#### Reminder: integrator-main-clearance

- **Owner:** Integration procedure.
- **Parameters:** none; project root and integrator session derive from the
  authenticated caller and current integration checkpoint.
- **Activation anchor:** immediately when repo-root main blocks synchronization.
- **Duration:** the existing ~2–3 minute interval owned by this procedure.
- **Recurrence:** recurring while repo-root main remains blocked.
- **Arm condition:** set on first dirty-main block before yielding.
- **Intent:** `Recheck whether repo-root main is clear. If clear, resume integration. Otherwise resolve each dirty path under the integration procedure and keep this reminder; when every remaining dirty path is escalated to a human, cancel it and hold as a beacon — the next move is theirs.`
- **Firing behavior:** re-enter `telec todo integrate` and follow
  **Resolving a dirty path** for each blocking path, identified per divergence
  shape as in **Blocked on dirty main** step 2: the listed dirty overlap when
  repo-root `main` is only behind, every path `git -C <root> status --short`
  reports when its history is split.
- **Cancellation:** cancel when main clears, the integration session reaches a
  terminal outcome, the human explicitly supersedes the wait, or every remaining
  dirty path has been escalated.
- **Invocation:** `telec reminders set integrator-main-clearance`.
<!-- /planned-change:integrator-stranded-dirt-by-asking -->

#### Reminder: integrator-queue-watch

- **Owner:** Integration procedure and its queue-empty state-machine formatter.
- **Parameters:** optional `after` override; the queue and integrator session
  derive from the authenticated caller.
- **Activation anchor:** immediately after a completed drain finds no eligible
  candidate and the singleton integrator parks.
- **Duration:** 15 minutes by default; an explicit caller interval replaces the
  default without changing this profile's intent.
- **Recurrence:** recurring while the integrator remains parked on an empty
  queue.
- **Arm condition:** set from the queue-empty outcome before yielding.
- **Intent:** `Recheck the integration queue and outstanding canonical-main maintenance from current source truth. Judge completed maintenance and recover failures within the integration lane; if a candidate is ready, continue the drain, otherwise remain parked.`
- **Firing behavior:** inspect checkout-scoped integrator judgment markers,
  outstanding maintenance records, and structured terminal outcomes for
  canonical-main activations, including direct commits with no todo candidate,
  through `telec code maintenance status`.
  Keep the judgment pending while any owed action is unfinished or failed.
  After terminal success, inspect the changed runtime and read logs from a
  window beginning no later than the earliest activation recorded on the
  marker; an earlier or narrower read does not discharge it. Retain unresolved
  judgment across reminder beats and route terminal failures through bounded
  recovery. Then
  invoke the integration state machine once. If it dequeues a candidate,
  cancel this watcher before continuing; if the queue remains empty, leave it
  live and execute the returned instruction verbatim.
- **Cancellation:** cancel when a candidate is dequeued, the integrator cedes
  its singleton role, the session is directed to end, or the watch is
  superseded.
- **Invocation:** `telec reminders set integrator-queue-watch`.

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

Park after bookkeeping completes. Hold `integrator-queue-watch` while awaiting
the next candidates, and end only when directed.

### When to end, when to wait, when to beacon

The integrator's terminal behavior has three shapes — do not collapse them:

- **Queue drained (INTEGRATION COMPLETE):** park on the prescribed recurring
  `integrator-queue-watch` and await the next candidates. The integrator is a
  singleton and is not re-dispatched; end only when directed.
<!-- planned-change:integrator-stranded-dirt-by-asking -->
- **Transient block (dirty main):** do not end and do not idle — keep
  `integrator-main-clearance` live
  until main clears, then continue the drain (see **REPO ROOT SYNC REQUIRED**). The
  block self-heals as concurrent agents commit.
<!-- change:integrator-stranded-dirt-by-asking -->
- **Transient block (dirty main):** do not end and do not idle — keep
  `integrator-main-clearance` live and resolve each dirty path until main clears,
  then continue the drain (see **REPO ROOT SYNC REQUIRED**).
<!-- /planned-change:integrator-stranded-dirt-by-asking -->
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
