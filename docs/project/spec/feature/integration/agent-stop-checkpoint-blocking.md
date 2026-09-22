---
description: Transcript (and other) evidence based checkpoint engine that may block an agent_stop hook with an
  adapter-formatted instruction nudging the agent to do obligated tasks/maintenance.
visibility: public
---

# Agent Stop Checkpoint Blocking — Spec

## What it is

A deterministic, zero-LLM heuristic engine invoked from the hook receiver
on agent-stop events. It reads the current turn's transcript, the working
tree's version-control state scoped to the turn window, and a session's
project context, then classifies changed files into categories (code,

tests, docs, configs, infra) and produces a checkpoint

result listing required actions. If any actions are required, the receiver
emits an adapter-formatted block decision that causes the agent CLI to
re-prompt itself with the checkpoint instruction.

Checkpoint evaluation consumes one complete native execution address. When
the normalized stop hook carries both a native session identifier and a
transcript path, the receiver selects that hook address while preserving the
resolved TeleClaude session as the lineage and state owner. When either hook
address member is absent, the receiver selects both members from the persisted
session row; it never combines members from different sources.

The receiver emits `checkpoint_evidence_address_resolved` at INFO for every
checkpoint evaluation that reaches address selection. The record carries the
receiver ingress identifier, TeleClaude session identifier, selected native
session identifier, selected transcript path, and `address_source` (`hook` or
`session_row`).

The engine is gated by flag markers, session-scoped unless stated otherwise:
a turn-scoped **clear flag** skips checkpoints for the current turn and is
hard-cleared at the next user-prompt-submit; turn scoping prevents ordinary
file-change checkpoints from re-firing after a checkpoint has been delivered;
a fixed-name **authored main commit
marker** is recorded when this session commits **code** on `main` through
the sealed `telec code commit` path and triggers only the post-commit
review gate. The review gate defers while the working tree still carries an
uncommitted change owing a commit, so the marker persists across those turns
rather than being consumed; it surfaces once on a turn with no pending commit
and is consumed then, or is consumed when the review is dispatched. A
force-fire that has nothing left to surface — no changed files, no required
actions, no observations, and no commit action — produces no checkpoint.
An **integrator-maintenance marker** carries canonical-root ranges whose
deterministic maintenance has completed and whose live-runtime log judgment
remains. It is keyed to the canonical checkout rather than to a session, so a
successor integrator inherits unfinished judgment without repeating mechanical
work. Log-check evidence discharges the marker.

The action and evidence ledger — what needs doing and what was done since
the turn started — is time-anchored to the turn window and is
wholesale-cleared at user-prompt-submit.

On a shared branch, version control is consulted only as the category oracle
(which file maps to which category), never as the arbiter of what is in-scope
or done; declarations answer that. In a todo worktree there is nothing to
arbitrate — the checkout is one todo's task scope with a single writer — so the
dirty tree is itself the scope and declarations are not consulted.

## Canonical fields

### Use cases

#### UC-CP1: Uncommitted code changes block stop

```gherkin
Given a Claude session has modified source files in the current turn
And no commit has been recorded since the last mutation
And the turn-scoped clear flag is not set
When Claude invokes the receiver with a Stop event
Then the checkpoint pre-emit step loads the session row
And resolves the project path (falling back to a transcript-derived working directory, adjusted for any worktree subdirectory)
And the turn-start timestamp is computed as the later of last user message and last checkpoint
And the heuristic engine evaluates the turn window
And the engine reports code category present with a required commit action
And a checkpoint message is composed listing required actions, prefixed so the receiver's system-prompt filter can drop the echoed prompt on the next turn
And a checkpoint-seen outbox entry is recorded with the current timestamp
And the Claude adapter formats a block decision carrying the message
And the receiver emits the block decision and exits cleanly BEFORE enqueueing the agent-stop event
```

#### UC-CP2: Turn-scoped clear flag skips checkpoint for the current turn

```gherkin
Given the session-scoped checkpoint clear flag is set
When the checkpoint pre-emit step runs
Then the per-turn recheck flag is cleared so a future re-enable can re-arm checkpoints cleanly
And a "checkpoint skipped (clear flag)" info log emits
And the checkpoint pre-emit returns no decision
And the receiver enqueues the agent-stop event normally without emitting a block response
(The clear flag is itself hard-cleared at the next user-prompt-submit, so the skip lasts one turn only.)
```

#### UC-CP3: No turn start → no checkpoint

```gherkin
Given the session row has neither a last user message timestamp nor a last checkpoint timestamp
When the turn-start resolver returns nothing
Then the checkpoint pre-emit step logs "checkpoint skipped (no turn start)" at debug
And returns no decision
And the receiver proceeds to enqueue the agent-stop event
```

#### UC-CP4: No turn-local changes → no checkpoint

```gherkin
Given the heuristic engine returns an empty checkpoint result (no required actions)
And no integrator-maintenance marker is present
When the checkpoint pre-emit step runs
Then a debug log records "checkpoint skipped: no turn-local changes"
And no decision is produced
And no checkpoint-seen entry is enqueued
And the agent-stop event enqueues normally
```

#### UC-CP5: Turn-scoped markers cleared on new user prompt

```gherkin
Given a checkpoint fired earlier in this turn and set the per-turn recheck flag
And the turn may carry a set clear flag
When a new user-prompt-submit hook arrives that is NOT system-injected
Then the per-turn recheck flag is consumed
And the turn-scoped clear flag is consumed
And the next agent-stop in the new turn may fire a fresh checkpoint
```

#### UC-CP5A: Main-branch post-commit review action follows code authorship

```gherkin
Given the current branch is main
And this session authored a main commit through the sealed `telec code commit` path
And the committed pathspec included code (not a doc-only commit)
And the session-scoped authored-main-commit marker is present
When the heuristic engine evaluates the turn window
Then the result includes the post-commit review-gate surfacing action
And that action instructs the authoring session to dispatch the commit(s) to independent review automatically
And waits for REVIEW COMPLETE before reporting completion
And routes a REQUEST CHANGES verdict through the author-owned remediation contract in `software-development/policy/commits`
And the authored-main-commit marker is consumed
(The authored-main-commit marker triggers only the review gate; the maintenance a commit's paths owe is performed at the commit boundary — see `project/spec/feature/integration/post-commit-maintenance`.)

Given the current branch is main
And this session authored a main commit through the sealed `telec code commit` path
And the committed pathspec contained only documentation (docs/**, *.md, *.txt, *.rst) with no code
When the commit gate runs
Then the authored-main-commit marker is NOT armed
And the next agent-stop produces no post-commit review-gate surfacing action for that commit
(Under doc-first, documentation is reviewed in the lifecycle, not at the post-commit review gate.)

Given the current branch is main
And HEAD moved because of a peer commit, `git pull --rebase`, merge, or other commit not authored by this session through the sealed path
And the session-scoped authored-main-commit marker is absent
And there are no turn-local dirty files
When the heuristic engine evaluates the turn window
Then it produces no checkpoint
And does not emit the post-commit review-gate surfacing action

Given the current branch is main
And the session-scoped authored-main-commit marker is present
And there are turn-local dirty files owing a commit action
When the heuristic engine evaluates the turn window
Then ordinary checkpoint classification still runs for those files
And the commit action is surfaced so the pending change is committed first
And the post-commit review-gate surfacing action is NOT emitted while a commit action is pending
And the authored-main-commit marker is NOT consumed, so the review gate surfaces on a later turn once the working tree owes no commit
And no system role, including integrator, is exempt from this code-authorship rule

Given the current branch is main
And the session-scoped authored-main-commit marker is present
And there are no turn-local dirty files owing a commit action
When the heuristic engine evaluates the turn window
Then the post-commit review-gate surfacing action is emitted once
And the authored-main-commit marker is consumed

Given the current branch is main
And the session-scoped authored-main-commit marker is present
And this turn's tool timeline contains a review dispatch for the commit(s) — a `telec sessions run` run whose `--command` value names the commit-review command, or a remediation `telec sessions send <reviewer> "review commits ..."` whose message payload begins with "review commits"
When the heuristic engine evaluates the turn window
Then the post-commit review-gate surfacing action is NOT emitted
And the authored-main-commit marker is consumed
And when no changed files, required actions, observations, or commit action remain, no checkpoint is produced rather than an empty "No code changes detected this turn." block
So the main-commit force-fire does not re-surface the review gate on a commit whose review was already dispatched
And a command that merely mentions the commit-review command in either form, without dispatching it (a different `--command`, or a question in a `telec sessions send` message), does not discharge the gate
```

#### UC-CP6: Per-adapter checkpoint response payloads

```gherkin
Given the receiver is acting on behalf of Claude, Codex, or Gemini
And each adapter supports hook checkpoints in v1
When the checkpoint pre-emit step returns a non-empty checkpoint reason
Then the active adapter formats:
    - Claude  → block decision with reason
    - Codex   → block decision with reason
    - Gemini  → deny  decision with reason
And the receiver emits the decision and exits cleanly BEFORE enqueueing the agent-stop event

Given a hypothetical adapter that does not support hook checkpoints
When the pre-emit early-return guard runs
Then it short-circuits before the heuristic engine runs and the agent-stop event enqueues normally
(No v1 adapter takes this branch.)
```

#### UC-CP7: Evaluation failure does not synthesize a checkpoint

```gherkin
Given checkpoint evaluation fails before it establishes a complete set of required maintenance actions
When the engine's outer guard catches the failure
Then the failure is recorded through the structured logging boundary
And the engine returns no checkpoint reason
And no checkpoint-seen entry is recorded for that failed evaluation
And no generic or exception-derived instruction is displayed
And the receiver proceeds to enqueue the agent-stop event normally
```

#### UC-CP8: Worktree subdir resolution for branch detection

```gherkin
Given the session's subdirectory marks it as a worktree session
When the checkpoint project-path resolver runs
Then it composes the project path with the worktree subdirectory into a single working path
And the heuristic engine runs branch detection against the worktree, not the repo root
```

#### UC-CP9: Recorded edits with pending commit evidence require the commit step

```gherkin
Given an agent session has turn-local file changes that owe no maintenance actions
And the runtime records edits to those files in the current checkpoint cycle
And the working tree carries uncommitted changes
And the cycle contains no commit evidence after the last recorded edit
When the checkpoint evaluates the agent-stop boundary
Then the agent receives a checkpoint requiring the commit step
```

#### UC-CP10: Code categories with no per-category action

```gherkin
Given the turn-local changes touch a code category with no per-category action (e.g. teleclaude/hooks/**, which auto-applies on next invocation)
And the session is on main
And no log-check or test evidence appears in the timeline yet
When the heuristic engine evaluates the turn window
Then the log-check and test categories appear in the changed-category summary
And the log-check and test actions are surfaced

Given the same code category change
And the session is on a non-main branch
And no log-check or test evidence appears in the timeline yet
When the heuristic engine evaluates the turn window
Then the log-check action is affirmatively recorded as deferred off-main
And the log-check category and action are omitted from the checkpoint
And the test category remains in the changed-category summary
And the test action is surfaced

Given the same code category change
And the available evidence satisfies every branch-eligible action
When the heuristic engine evaluates the turn window
Then every branch-eligible category still appears in the changed-category summary
And no action is surfaced, because its evidence was observed
(The changed-category summary reports the branch-eligible category set, independent of evidence suppression. Off-main deferrals are separate affirmative decisions and never appear as required actions.)
```

#### UC-CP11: Integrator post-advance log-check force-fire

```gherkin
Given a session whose role is integrator
And integration advanced repository-root main and completed deterministic maintenance for the advanced range
And that range owes a live-runtime log check
When the heuristic engine evaluates the turn window
Then the checkpoint force-fires even though no turn-local Edit or Write change exists
And it surfaces only the log-check action for the accumulated range
And no install, dependency, restart, reload, sync, review, commit, or test action is surfaced from that marker
```

#### UC-CP29: Main movement without a log marker creates no checkpoint

```gherkin
Given a session whose role is not integrator
And repository-root main advanced for any reason
And no checkout-scoped log-check marker is present
When the heuristic engine evaluates the turn window
Then no checkpoint is force-fired on account of the moved main HEAD
```

#### UC-CP13: Parent snippet edited without its pending companion

```gherkin
Given a turn edits a live parent doc snippet `<stem>.md`
And a pending companion sibling `<stem>.<slug>.md` exists on disk
And the companion is NOT in the turn's changed files
When the heuristic engine evaluates the turn window
Then the result surfaces an action telling the agent to mirror the parent edit into the companion
(else the companion clobbers the parent edit when it replaces the parent at delivery)

Given a turn edits a live parent doc snippet `<stem>.md`
And its pending companion sibling `<stem>.<slug>.md` is also in the turn's changed files
When the heuristic engine evaluates the turn window
Then no companion-drift action is surfaced (the edit is mirrored)

Given a turn edits a doc snippet `<stem>.md` that has no companion sibling on disk
When the heuristic engine evaluates the turn window
Then no companion-drift action is surfaced

Given a turn edits only a companion `<stem>.<slug>.md` (not its parent)
When the heuristic engine evaluates the turn window
Then no companion-drift action is surfaced
(The check is a filename-derived presence test over the changed set; whether the
companion is a correct mirror of the parent is the reviewer's judgment, not the
checkpoint's.)
```

#### UC-CP14: Daemon-code categorization covers top-level and daemon-imported modules

```gherkin
Given a session commits a top-level daemon module directly under `teleclaude/` (e.g. `teleclaude/constants.py`, `teleclaude/daemon.py`) through the sealed `telec code commit` path
When the merged model resolves what that path owes
Then the file is categorized as daemon code
And the restart maintenance action is among the actions it owes
(Daemon-code categorization covers every daemon Python module at any depth under `teleclaude/`, top-level files included — not only nested ones.)

Given a session commits a CLI module the daemon imports at load (e.g. `teleclaude/cli/telec/surface.py`, held by `teleclaude/core/tool_access.py`)
When the merged model resolves what that path owes
Then the file is categorized as daemon code
And the restart maintenance action is among the actions it owes
(A CLI module the daemon imports at startup changes daemon runtime behavior, so the daemon-code category includes it despite the general CLI-subprocess exclusion.)

Given a session commits a CLI module that runs only as a per-invocation subprocess and is not imported by the daemon
When the merged model resolves what that path owes
Then the file is not categorized as daemon code
And the restart maintenance action is not among the actions it owes
(The boundary is daemon-import membership, not directory: only CLI modules the daemon holds at runtime require a restart.)
```

#### UC-CP18: A clean working tree raises no commit action

```gherkin
Given the heuristic engine evaluates a turn
And the working tree is definitively clean (git status --porcelain --untracked-files=all is empty)
And another process committed a file into that working tree after the turn anchor
When the engine decides whether a commit action is owed
Then the commit action is not required
And no checkpoint is produced for the commit reason

Given the heuristic engine evaluates a turn
And the working tree carries an uncommitted change (git status --porcelain --untracked-files=all is non-empty)
When the engine decides whether a commit action is owed
Then the existing commit-action decision is applied unchanged

Given the heuristic engine evaluates a turn
And the working-tree status cannot be read
When the engine decides whether a commit action is owed
Then the existing commit-action decision is applied unchanged
(There is nothing to commit when nothing is uncommitted; a path committed since the turn anchor is not uncommitted work. The clean-tree suppression is a guaranteed floor over the existing decision — it can only withhold a commit action on a provably clean tree, never add one, and it defers to the existing decision whenever the tree is dirty or its state is unreadable.)
```

#### UC-CP19: A turn's own commit is not counted as a mutation of the files it commits

```gherkin
Given a turn's only turn-local change to the attributed files is a sealed `telec code commit ... --only <files>` that commits exactly those files
And the committed files are documentation only, so no other required action or observation is owed
And the working tree is dirty from an unrelated concurrent change, so the clean-tree commit-action floor (UC-CP18) does not apply
When the heuristic engine decides whether a commit action is owed
Then the commit is recognized as the evidence that discharges the commit obligation for those files
And the commit action is not required
And no "No code changes detected this turn" checkpoint is produced

Given a turn edits a file and then commits it via a sealed `telec code commit` in the same turn
When the heuristic engine decides whether a commit action is owed
Then the edit is the last mutation and the later commit discharges it
And the commit action is not required
(A commit persists already-made mutations; it is never itself a mutation of the files it commits, so it can never be the last mutation those files must be committed after — the self-referential ordering that would demand a commit strictly after the commit is excluded.)
```

#### UC-CP20: Post-advance log judgment begins with a range-only marker

```gherkin
Given integration completes deterministic maintenance for a canonical-root advancement whose paths owe log-check
When it records the checkout-scoped marker
Then the marker carries the advanced range and no mechanical action id
```

#### UC-CP30: Post-delivery log markers accumulate ranges

```gherkin
Given another qualifying advancement occurs before log-check evidence is observed
When its range is recorded
Then the marker accumulates both ranges
```

#### UC-CP31: Log evidence discharges the range marker

```gherkin
Given the integrator runs the applicable log check
When a later agent-stop observes that evidence
Then the marker is removed and no post-delivery checkpoint force-fires for those ranges again
```

#### UC-CP32: A successor integrator inherits unfinished log judgment

```gherkin
Given the integrator session ends while the marker remains
And another integrator acquires the lease for the same checkout
When the heuristic engine evaluates that session
Then the accumulated log-check obligation is surfaced to the successor
```

#### UC-CP23: Worktree checkpoints omit live-runtime log checks

```gherkin
Given an agent session is working from a non-main todo worktree
And its turn-local changes match a scope that ordinarily owes a live-runtime log check
When the checkpoint engine evaluates the agent-stop boundary
Then the worktree checkpoint omits the live-runtime log-check action
And any other worktree-eligible actions remain unchanged

Given an agent session is working from main
And its turn-local changes match the same scope
And no current-cycle log-check evidence exists
When the checkpoint engine evaluates the agent-stop boundary
Then the live-runtime log-check action remains eligible
```

#### UC-CP24: Actionless checkpoint evaluation is silent

```gherkin
Given an agent session reaches an agent-stop checkpoint boundary
And every obligation in the current checkpoint cycle is either satisfied or ineligible at this working location
And no commit action, review action, required observation, or other required action remains
When checkpoint evaluation completes
Then no checkpoint decision is produced
And the agent stop is not blocked by an all-clear message
```

#### UC-CP25: Checkpoint reasons use the hook-boundary control envelope

```gherkin
Given a Claude, Codex, or Gemini agent session reaches a checkpoint hook boundary
When TeleClaude delivers a non-empty checkpoint reason to that agent runtime
Then the reason is framed by the canonical XML checkpoint control envelope
And no bracket checkpoint envelope is emitted on the hook boundary
```

#### UC-CP28: Maintenance the commit boundary performs is not an agent obligation

```gherkin
Given a session commits daemon code through the sealed `telec code commit` path on the canonical checkout's main branch
And the committed paths resolve a non-empty set of main-only maintenance actions
When the heuristic engine evaluates the turn window
Then no maintenance action is surfaced for that commit
And no maintenance obligation persists into a later checkpoint cycle of that turn
And the post-commit review-gate action is still surfaced for the committed code (per UC-CP5A)
(The maintenance ran at the commit boundary; asking the agent to repeat it would ask for work already done, on evidence a transcript cannot carry.)

Given the same turn also changed paths owing a judgment action
And no evidence for that judgment action appears in the timeline
When the heuristic engine evaluates the turn window
Then the judgment action is surfaced
(The engine resolves the checkpoint registry alone, so a maintenance action a binding names is not a checkpoint obligation at all; log-check and test remain the agent's.)
```

#### UC-CP26: The checkpoint names the session's own undelivered work

```gherkin
Given an agent session on a shared branch reaches an agent-stop checkpoint boundary
And the session has declared paths that are dirty and not yet committed
When checkpoint evaluation completes
Then a checkpoint decision is produced rather than skipped as having no changes
And the decision names those paths
And its required action instructs the agent to commit them
```

#### UC-CP33: Dirty paths the session never declared raise no obligation

```gherkin
Given an agent session on a shared branch reaches an agent-stop checkpoint boundary
And the working tree holds dirty paths that session has not declared
When checkpoint evaluation completes
Then no obligation is raised for those paths
And any decision produced for another reason names none of them
```

#### UC-CP34: A worktree's obligation is its dirty tree, not its declarations

```gherkin
Given an agent session is working from a non-main todo worktree
And that worktree holds dirty paths the session has declared none of
When checkpoint evaluation completes
Then a checkpoint decision is produced naming those paths
And its required actions are the ones their categories carry
```

### Cross-context references

- Belongs to `agent_runtime` in the v2 fold; inventoried in v1 alongside
  the receiver it composes with.
- Reads session row state owned by `agent_runtime`: last user message
  timestamp, last checkpoint timestamp, native log file, working
  subdirectory, project path, turn anchor SHA,
  native session id, and `system_role` (e.g. `"integrator"`) — the role
  is passed to `get_checkpoint_content` and stored in `CheckpointContext`
  to gate the integrator-maintenance force-fire path.
- Reads the session's working slug for structured checkpoint diagnostics.
- Consumes the checkout-scoped range marker written after integration completes
  deterministic maintenance, and surfaces only the remaining live-runtime log
  judgment.
- Writes checkpoint-seen entries that `session-state-mutation-via-outbox`
  consumes to update last-checkpoint timestamp.

## Known caveats

- Session-scoped flag markers live in a per-session temporary directory;
  identifiers that contain unsafe characters are hashed to a digest
  component for the filesystem path. The integrator-maintenance marker is
  the one exception: it is addressed by the canonical checkout, so it lives
  under a checkout-derived component and is reachable by every session
  working from that checkout.

- The clear flag is turn-scoped: it skips checkpoints for the current turn
  and is hard-cleared at the next non-system user-prompt-submit. A checkpoint
  that recurs across turns is a
  signal that the heuristics are over-tight — the agent surfaces it to the
  human rather than re-setting the flag. The recheck loop-guard is the
  involuntary backstop against an evidence-miss spinning forever.
- The main-branch post-commit review gate is driven by a session-scoped
  authored-main-commit latch recorded by `telec code commit` only for
  commits whose pathspec includes code, then consumed when the review
  action surfaces. The latch triggers only the review gate — never the
  action or evidence ledger. It is not SHA-keyed, so rebases and peer HEAD
  movement do not re-arm it; doc-only commits do not arm it; raw
  `git commit` does not mark authorship.

- An integration fast-forward that produces no repository-root commit invokes
  deterministic maintenance directly from canonical root. The checkout-scoped
  marker carries only ranges awaiting log judgment, so a successor integrator
  inherits the judgment without repeating maintenance.

- Heuristics are zero-LLM and deterministic — pattern matching on
  version-control state and the transcript, no API calls.
- The engine is project-aware: it may short-circuit early for projects
  outside the supported set (the engine's project-allowlist policy
  lives in the engine itself).
- Worktree-aware path resolution composes the project path with the worktree
  subdirectory so branch detection evaluates the actual checkout. Mechanical
  actions never surface from checkpoint location rules; the integrator receives
  only checkout-scoped log judgment after canonical-root maintenance.
- Unknown agent names fall back to the default agent — a pragmatic
  guard against unrecognized agent values.
- All three v1 adapters support hook checkpoints. Claude and Codex
  emit block decisions; Gemini emits a deny decision. The shape
  differences track each agent CLI's stdin protocol for blocking
  continuations.
- The checkpoint message is prefixed so the receiver's system-prompt
  filter can drop the echoed prompt when the agent re-submits it on
  the next turn.

## See Also

- docs/project/adr/0037-checkpoint-ledger-separates-commit-detection.md
- docs/project/adr/0038-companion-drift-caught-at-checkpoint.md
- docs/project/adr/0070-clean-working-tree-floors-the-commit-action-checkpoint.md
- docs/project/adr/0086-checkpoint-failures-do-not-invent-work.md
