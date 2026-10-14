---
description: 'Integration phase. Drive the integration state machine, handle squash commits, conflicts, push rejections, and lease contention.'
visibility: 'public'
role: integrator
parameters:
  - name: slug
dispatch:
  agent: [codex, claude, gemini, deepseek]
  thinking_mode: slow
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
  override; the wrapper matrix in `docs/local/design/code-commit.md` carries the rule.
- **The agent's cwd is the integration worktree.** All git and make commands run from
  there without `-C` prefixes. Commands targeting project root (repo sync) are emitted
  by the engine with explicit `-C <project_root>` paths. **The worktree's index and
  working tree belong to the state machine.** Only `telec todo integrate` and the
  `telec code commit` instructions it emits write to them. Read-only git commands —
  `status`, `log`, `show`, `diff <ref>..<ref>`, `rev-parse` — are fine. Mutating
  commands inside the worktree are gated per the wrapper matrix (see
  `docs/local/design/code-commit.md`): `stash` is absolutely blocked everywhere
  (no role carve-out — stash is too coarse for a multi-agent repo); `checkout <ref>
-- <path>`, `restore <path>`, and `restore --source <ref> <path>` require the
  `--confirmed` flag after reading the printed inspection checklist; pathspec
  `reset HEAD <path>` / `restore --staged <path>` are index-only and allowed
  without ceremony. The `--confirmed` friction is the integrator's deliberate
  ratification that the working-tree mutation has been inspected and will not
  silently overwrite intentional state before the next bookkeeping commit.
- **When repo-root sync is blocked by dirty files**, the integrator never stashes,
  overwrites, or rebases across them, and discards one only by an evidenced revert.
  It waits on `integrator-main-clearance` and resolves each dirty path on its own:
  it routes a declared path to its owner, asks only the sessions whose history shows
  they wrote an undeclared path, and commits the path as-is once it is quiet and
  unclaimed (see **REPO ROOT SYNC REQUIRED** below). The state machine emits this
  guidance when it observes the divergence.

<!-- planned:installation-activation-inspection -->

### Resolve the delivery assignment

Resolve the source checkout and delivery purpose before starting the queue
watcher or entering the integration state machine. This procedure owns upstream mainline delivery. Installation-only
assessment enters `sdlc/procedure/maintenance/installation-inspection` with its
retained activation rather than this source-delivery loop. When source delivery
owes runtime judgment, consume the installed activation's assessment through
its owning surface; do not start competing recovery
(`general/principle/trust-and-guardrails`).

One session holds a checkout's assessment responsibility at a time. The
integrator takes it when no live session holds it, and then performs the
judgment and recovery steps below itself. When another session holds it, the
maintenance recovery surface names that holder; leave recovery and judgment
with it, and publish an ahead canonical local main head only after the
assessment status records its completion for that head.
<!-- /planned:installation-activation-inspection -->

<!-- planned:reviewed-pr-contributions -->

### Contributor handoff

A contributor assignment follows its project's contribution contract and retains
PR acceptance as a separate fact. Its source handoff uses that contract's
proposal operation before any mainline queue watcher or integration call.
<!-- /planned:reviewed-pr-contributions -->

## Steps

<!-- planned-change:installation-activation-inspection -->

1. Set `integrator-queue-watch` first, then call `telec todo integrate [slug]` to
   enter the state machine. The watch stays live for as long as this session is the
   integrator; never cancel it. It is the integrator's standing way back to the
   state machine, and a session that ends removes it.

2. The call returns an operation receipt and does not wait for the machine. Yield;
   when the operation's outcome wakes this session, read the instruction block
   with `telec operations get <operation_id>` and execute it verbatim.

3. After executing, call `telec todo integrate` again to advance.
   3a. After a canonical-main advancement, inspect the maintenance actions recorded
   for that activation. Treat pending actions as pending, judge terminal
   failures and recover within the integration lane, and keep outstanding
   live-runtime judgment with the integrator. Continue observing those actions
   on `integrator-queue-watch` beats when they outlive this drain.
   After each activation, read that delivery's log window with knowledge of
   the change. Investigate anomalies, handle bounded recovery, and route
   remaining breakage for a forward fix through the normal bug process.
   For direct commits on canonical local main, judge any owed log window before
   publication. If the activated change is sound, push the current committed
   main head to origin/main from the project root with `git push origin main:main`
   and verify origin/main contains that exact head. A material activation failure leaves it local until recovery
   and a new log judgment; a successful log command alone is not a soundness
   verdict. A direct commit with no live-runtime log judgment is published after
   its owed maintenance succeeds. The committer owns review and remediation under
   `general/policy/commits`; the integrator does not inspect or wait for other
   sessions' review verdicts. Uncommitted repo-root paths are not part of the
   push and do not block it. The candidate pre-push checks in step 5 do not gate
   direct-main publication.
   `telec code maintenance status` reports the checkout's outstanding actions,
   terminal failures, and integrator judgment, each with its recovery command.
   After the cause of a terminal failure is addressed, `telec code maintenance
retry` replays that action for its original activation; `telec code
maintenance drain` resumes interrupted work and records maintenance
   readiness when no owed action remains.
4. Repeat until a terminal instruction is returned (COMPLETE or LEASE_BUSY).
5. Before a candidate push from the integration worktree, run repo-wide verification:
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

<!-- change:installation-activation-inspection -->

1. Set `integrator-queue-watch` first, then call `telec todo integrate [slug]` to
   enter the state machine. The watch stays live for as long as this session is the
   integrator; never cancel it. It is the integrator's standing way back to the
   state machine, and a session that ends removes it.

2. The call returns an operation receipt and does not wait for the machine. Yield;
   when the operation's outcome wakes this session, read the instruction block
   with `telec operations get <operation_id>` and execute it verbatim.

3. After executing, call `telec todo integrate` again to advance.
   3a. After a canonical-main advancement, inspect the maintenance actions recorded
   for that activation. While the integrator holds the checkout's assessment
   responsibility (see **Resolve the delivery assignment**), treat pending
   actions as pending, judge terminal failures and recover within the
   integration lane, and keep outstanding live-runtime judgment with the
   integrator. While another session holds it, that session keeps the recovery
   and the judgment, and the integrator observes its recorded outcome. Continue
   observing those actions on `integrator-queue-watch` beats when they outlive
   this drain.
   After each activation whose assessment the integrator holds, read that
   delivery's log window with knowledge of the change. Investigate anomalies,
   handle bounded recovery, and route remaining breakage for a forward fix
   through the normal bug process.
   For direct commits on canonical local main, judge any owed log window before
   publication, or, when another session holds the assessment, publish only
   after its recorded completion covers the head. If the activated change is sound, push the current committed
   main head to origin/main from the project root with `git push origin main:main`
   and verify origin/main contains that exact head. A material activation failure leaves it local until recovery
   and a new log judgment; a successful log command alone is not a soundness
   verdict. A direct commit with no live-runtime log judgment is published after
   its owed maintenance succeeds. The committer owns review and remediation under
   `general/policy/commits`; the integrator does not inspect or wait for other
   sessions' review verdicts. Uncommitted repo-root paths are not part of the
   push and do not block it. The candidate pre-push checks in step 5 do not gate
   direct-main publication.
   `telec code maintenance status` reports the checkout's outstanding actions,
   terminal failures, and integrator judgment, each with its recovery command.
   After the cause of a terminal failure is addressed, `telec code maintenance
retry` replays that action for its original activation; `telec code
maintenance drain` resumes interrupted work and records maintenance
   readiness when no owed action remains.
4. Repeat until a terminal instruction is returned (COMPLETE or LEASE_BUSY).
5. Before a candidate push from the integration worktree, run repo-wide verification:
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

<!-- /planned-change:installation-activation-inspection -->

The state machine returns one of the following instruction blocks at each step.

### SQUASH COMMIT REQUIRED

The branch has been squash-merged; staged changes are ready.

1. Read the context: diff stats, branch commit history, `prd`, optional
   `architecture` when present, and `implementation-plan`.
2. Compose a commit message capturing the full delivery intent:
   - Subject: imperative, scoped — e.g. `feat(my-feature): deliver my-feature`
   - Body: summarize what changed, key decisions, scope
   - Footer: none. Attribution and provenance are stamped by the sealed commit
     surface, not composed here; `general/policy/commits` is the
     canonical source and this procedure does not restate it.
3. Run `telec code commit --approved '<message>'`, then call `telec todo integrate`.
4. When the state machine reaches push, `telec code lint --all` and `telec code test --all` must already be green.

### Held clean candidate recovery

A held candidate with a clean squash and no integration commit can be returned
through `telec todo integrate --abandon`. Inspect the stage and retained candidate
branch first: the reset must discard only reproducible squash work, with no unique
integration edits. The machine requires a live hold and HEAD equal to the frozen
pre-merge SHA, resets only its integration worktree, and parks the attempt while
preserving the candidate branch, todo and hold. It refuses conflicted or committed
attempts.

Parking does not invalidate the plan or finalize handoff. For a corrected input,
route the findings to an orchestrator that can start an authentic work session.
That session independently grounds an explicit `--kickback` before invoking
`todo work`; work entry releases the hold and must not come first. Confirm the
kickback before releasing the hold for preparation. Keep the integration queue
watch live and continue unrelated candidates.

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
     Still blocked → load this procedure's current contract with
     `telec docs get sdlc/procedure/lifecycle/integrate` before acting on the
     decision. The returned decision identifies the dirty paths that block
     synchronization: the listed dirty overlap when repo-root `main` is only behind,
     and every path `git -C <root> status --short` reports when its history is split.
     Resolve each blocking path under **Resolving a dirty path** below, keep the
     reminder live, and wait again. A dirty path the decision does not identify as
     blocking is left alone.

  While waiting you are not idle: you hold the lease and the in-flight candidate is
  already committed, ready to push the instant main clears.

- **Git operation failure:** Fetch, repository-state inspection, fast-forward, and
  bookkeeping-push failures render a distinct **INTEGRATION ERROR** outcome rather than
  a divergence instruction. The integrator stays active, executes the emitted recovery
  steps within its governance, and re-enters `telec todo integrate`; the failure never
  parks the integrator merely because the failed operation was implied by its task.

#### Resolving a dirty path

On each `integrator-main-clearance` beat, run `telec code owners` once, then take
each blocking path on its own. Each path keeps its own history of what was sent and
claimed; a set of paths is never treated as one unit.

1. **Declared.** A path with a live declaring session belongs to that session. Send
   each owner one message listing all of its blocking paths, using step 4's message,
   and never send it the same path again. Wait for its commit.
2. **Recently written.** An undeclared path last modified within the current reminder
   interval is being worked on. Leave it for a later beat: its writer's own
   checkpoint may yet turn it into a declaration.
3. **Named by a pending-doc marker.** When an undeclared path's uncommitted diff adds
   a pending marker naming a todo slug — a `planned:<slug>` or
   `planned-change:<slug>` block, a `<stem>.<slug>.md` companion, or a
   `delivered_by` entry — that todo's prepare orchestrator wrote it. Find that
   session from the todo's state (`telec todo show <slug>`). If it is live, send it
   the path under step 4's message. If it is gone, read its transcript
   (`telec history show <session-id>`) together with the todo's state and resolve
   the path from that evidence under step 6.
4. **Ask the writer.** For every other quiet undeclared path, find the sessions whose
   history touched it with `telec history search <path> --project <project>`. Send
   each live session found, once, one message listing its paths:
   `These paths are dirty on main and block integration: <paths>. If you were in the middle of work, arm halt-to-respond first. Then: for each path that is yours, commit it now if it is ready and released for commit, otherwise reply that you are still working on it; if none are yours, end your turn with NOOP.`
   No other session is asked. When the search finds no live session, the path goes
   to step 6.
5. **Claimed.** A session that replies that a path is its own and still in progress
   owns that path. Keep waiting for its commit.
6. **Quiet and unclaimed on a later beat.** A path still dirty, not recently written,
   and claimed by no one — whether the sessions asked stayed silent or none was
   found — is committed as-is with a pathspec-scoped
   `telec code commit --approved --only <path>` under a message that names it as
   stranded work. Revert it instead only when session history clearly shows the work
   was abandoned, such as a path whose pending-doc markers name a todo that is removed
   or delivered while its prepare orchestrator's transcript shows the work was
   dropped. When that history cannot be read, commit and never revert.
7. **Escalate** to the human, once per path, only when an owner or claimant leaves its
   path uncommitted for three consecutive beats after it was messaged or claimed, or
   when a path's diff is unintelligible. Report each escalated path once, leave it
   untouched, and hold as its blocker beacon. `integrator-queue-watch` beats keep
   re-entering the state machine, and the drain resumes on the first beat after the
   path is committed.

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
  dirty path has been escalated. `integrator-queue-watch` stays live in every case
  and keeps re-entering the state machine.
- **Invocation:** `telec reminders set integrator-main-clearance`.

#### Reminder: integrator-queue-watch

<!-- planned-change:installation-activation-inspection -->

- **Owner:** Integration procedure and its queue-empty state-machine formatter.
- **Parameters:** optional `after` override; the queue and integrator session
  derive from the authenticated caller.
- **Activation anchor:** session entry, before the first state-machine call.
- **Duration:** 15 minutes by default; an explicit caller interval replaces the
  default without changing this profile's intent.
- **Recurrence:** recurring for as long as this session is the integrator —
  through drains, blocks, escalations, and parked queues alike.
- **Arm condition:** set first, unconditionally. Setting it again replaces it
  atomically without an unarmed gap.
- **Intent:** `Recheck the integration queue and outstanding canonical-main maintenance from current source truth. Judge completed maintenance and recover failures within the integration lane; if a candidate is ready, continue the drain, otherwise remain parked.`
- **Firing behavior:** inspect checkout-scoped integrator judgment markers,
  outstanding maintenance records, and structured terminal outcomes for
  canonical-main activations, including direct commits with no todo candidate,
  through `telec code maintenance status`.
  Keep the judgment pending while any owed action is unfinished or failed.
  After terminal success, read logs from a
  window beginning no later than the earliest activation recorded on the
  marker; an earlier or narrower read does not discharge it. Retain unresolved
  judgment across reminder beats and route terminal failures through bounded
  recovery. Apply the standing post-activation log judgment and direct-main
  publication in step 3a before invoking the integration state machine once,
  then execute the returned instruction verbatim.
- **Cancellation:** none while this session is the integrator (step 1). The
  reminder is removed when the session ends, and only the human ends an
  integrator.
- **Invocation:** `telec reminders set integrator-queue-watch`.

<!-- change:installation-activation-inspection -->

- **Owner:** Integration procedure and its queue-empty state-machine formatter.
- **Parameters:** optional `after` override; the queue and integrator session
  derive from the authenticated caller.
- **Activation anchor:** session entry, before the first state-machine call.
- **Duration:** 15 minutes by default; an explicit caller interval replaces the
  default without changing this profile's intent.
- **Recurrence:** recurring for as long as this session is the integrator —
  through drains, blocks, escalations, and parked queues alike.
- **Arm condition:** set first, unconditionally. Setting it again replaces it
  atomically without an unarmed gap.
- **Intent:** `Recheck the integration queue and outstanding canonical-main maintenance from current source truth. Judge completed maintenance and recover failures within the integration lane; if a candidate is ready, continue the drain, otherwise remain parked.`
- **Firing behavior:** inspect the checkout's assessment record, its
  responsibility holder, outstanding maintenance records, and structured
  terminal outcomes for canonical-main activations, including direct commits
  with no todo candidate, through `telec code maintenance status`.
  Keep the judgment pending while any owed action is unfinished or failed.
  While the integrator holds the assessment, after terminal success read logs
  from a window beginning no later than the earliest activation recorded on the
  record; an earlier or narrower read does not complete it. Retain unresolved
  judgment across reminder beats and route terminal failures through bounded
  recovery. While another session holds it, leave recovery and judgment with
  that holder and observe its recorded outcome. Apply the standing post-activation log judgment and direct-main
  publication in step 3a before invoking the integration state machine once,
  then execute the returned instruction verbatim.
- **Cancellation:** none while this session is the integrator (step 1). The
  reminder is removed when the session ends, and only the human ends an
  integrator.
- **Invocation:** `telec reminders set integrator-queue-watch`.

<!-- /planned-change:installation-activation-inspection -->

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

All candidates have been processed. The queue-empty result does not publish
ordinary direct commits on repository-root main. Inspect local main against
origin/main before parking. If local main is ahead, complete its owed maintenance
and any live-runtime log judgment, push the committed head from the project
root, and verify origin/main contains it. Other sessions' review state and
unrelated uncommitted repo-root paths are not publication gates. A rejected push
or split history follows REPO ROOT SYNC REQUIRED; only paths that block that
reconciliation enter its dirty-path procedure.

Park after bookkeeping completes, with `integrator-queue-watch` live, and end only
when directed.

### When to end, when to wait, when to beacon

The integrator's terminal behavior has three shapes — do not collapse them. In
every shape `integrator-queue-watch` stays live.

- **Queue drained (INTEGRATION COMPLETE):** park on `integrator-queue-watch` and
  await the next candidates. The integrator is a
  singleton and is not re-dispatched; end only when directed.
- **Transient block (dirty main):** do not end and do not idle — keep
  `integrator-main-clearance` live and resolve each dirty path until main clears,
  then continue the drain (see **REPO ROOT SYNC REQUIRED**).
- **Unrecoverable block (genuine human decision):** stay alive as a beacon, but only
  after recovery and the retry window are exhausted, so the human sees and intervenes.
  The queue watch keeps re-entering the state machine, so the drain resumes on the
  first beat after the human acts.

## Outputs

- Merged candidates on canonical main (pushed from integration worktree).
- Direct commits on repository-root main published after their maintenance and
  any owed log judgment, with the checked head confirmed on origin/main.
- Cleaned worktrees and branches.
- `integration.*` lifecycle events at each state transition.

## Recovery

The state machine checkpoint is crash-safe. If the integrator process dies at any
point, re-calling `telec todo integrate` reads the durable checkpoint and resumes
from the last persisted phase. No manual checkpoint editing is required.

### Agent-actionable recovery

- **Held clean uncommitted attempt:** Inspect retained source and stage, then use
  `telec todo integrate --abandon` under **Held clean candidate recovery** above.

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
