---
description: 'Heuristic checkpoint engine that may block an agent_stop hook with an adapter-formatted instruction nudging the agent to commit, run tests, fix lint, run telec sync, or surface post-merge maintenance to the integrator.'
visibility: 'public'
---

# Agent Stop Checkpoint Blocking — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A deterministic, zero-LLM heuristic engine invoked from the hook receiver
on agent-stop events. It reads the current turn's transcript, the working
tree's version-control state scoped to the turn window, and a session's
project context, then classifies changed files into categories (code,
tests, docs, configs, infra, sync-validation) and produces a checkpoint
result listing required actions. If any actions are required, the receiver
emits an adapter-formatted block decision that causes the agent CLI to
re-prompt itself with the checkpoint instruction.

The engine is gated by session-scoped flag markers: a turn-scoped **clear
flag** skips checkpoints for the current turn and is hard-cleared at the
next user-prompt-submit; turn scoping prevents ordinary file-change
checkpoints from re-firing after a checkpoint has been delivered; a
**commit-obligation ledger**, carrying outstanding `main_only` maintenance
actions derived from every sealed `telec code commit` in the turn, sources
those actions into the action ledger so committing does not empty it; each
obligation discharges when its evidence is observed, and the ledger is
hard-cleared at user-prompt-submit; a fixed-name **authored main commit
marker** is recorded when this session commits **code** on `main` through
the sealed `telec code commit` path and triggers only the post-commit
review gate, then is consumed when that review action is surfaced; and an
**integrator-maintenance marker**, carrying the delivered merge range, is
recorded by the integration state machine when it advances repo-root
`main`, then consumed when the integrator's post-merge maintenance
checkpoint is surfaced.

The action and evidence ledger — what needs doing and what was done since
the turn started — is time-anchored to the turn window and includes
outstanding commit obligations; each obligation is hard-cleared when evidence
discharges it, and the ledger is wholesale-cleared at user-prompt-submit.

Version control is consulted only as the category oracle (which file maps
to which category), never as the arbiter of what is in-scope or done.

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
And no commit-obligation ledger entry is present
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
And the turn may carry a set clear flag and commit-obligation ledger entries
When a new user-prompt-submit hook arrives that is NOT system-injected
Then the per-turn recheck flag is consumed
And the turn-scoped clear flag is consumed
And the commit-obligation ledger is consumed
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
And that action instructs the agent to set a non-blocking 5-minute heartbeat when it recommends review
And if that heartbeat fires without a user response approving or declining review, the agent dispatches the commit(s) to review
And waits for REVIEW COMPLETE before reporting completion
And the authored-main-commit marker is consumed
(The authored-main-commit marker triggers only the review gate; commit-derived maintenance flows through the commit-obligation ledger — see UC-CP12.)

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
And no commit-obligation ledger entry is present
And there are no turn-local dirty files
When the heuristic engine evaluates the turn window
Then it produces no checkpoint
And does not emit the post-commit review-gate surfacing action

Given the current branch is main
And the session-scoped authored-main-commit marker is present
And there are turn-local dirty files
When the heuristic engine evaluates the turn window
Then ordinary checkpoint classification still runs for those files
And the post-commit review-gate surfacing action is emitted once
And the authored-main-commit marker is consumed
And the commit action is suppressed only by commit evidence in the turn timeline, not by the authored-main-commit marker
And no system role, including integrator, is exempt from this code-authorship rule

Given the current branch is main
And the session-scoped authored-main-commit marker is present
And this turn's tool timeline contains a review dispatch for the commit(s) — a `telec sessions run --command /next-review-commits ...` run, or a remediation `telec sessions send <reviewer> "review commits ..."` whose message payload begins with "review commits"
When the heuristic engine evaluates the turn window
Then the post-commit review-gate surfacing action is NOT emitted
And the authored-main-commit marker is consumed
So the main-commit force-fire does not re-surface the review gate on a commit whose review was already dispatched
And a command that merely mentions `/next-review-commits` without dispatching it (a different `--command`, or a question in a `telec sessions send` message) does not discharge the gate
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

#### UC-CP7: Heuristic engine fail-open returns fallback message

```gherkin
Given the heuristic engine hits an internal failure (transcript read error, version-control error, evidence-gathering exception)
When the engine's outer guard catches the exception
Then the engine returns a fail-open fallback checkpoint message — NOT nothing
And the checkpoint pre-emit step treats the fallback as a non-empty reason
And a checkpoint-seen outbox entry is recorded with the current timestamp
And the adapter formats the block decision around the fallback message
And the receiver emits the decision and exits cleanly
And the agent-stop event is NOT enqueued (the receiver exited before reaching enqueue)

Given the checkpoint pre-emit step ITSELF raises (attribute error, type error, value error, persistence error) OUTSIDE the engine's guard
When the surrounding step catches it
Then a warning "checkpoint eval crashed (ignored)" is emitted
And no block decision is emitted
And the receiver proceeds to enqueue the agent-stop event normally
This second branch covers unexpected failures that escape the engine's guard.
It does NOT cover persistence errors that occur while loading the checkpoint
row: that path catches locally, logs "checkpoint eval skipped (db error)" at
debug, returns no decision, and checkpoint evaluation returns no block.
```

#### UC-CP8: Worktree subdir resolution for branch detection

```gherkin
Given the session's subdirectory marks it as a worktree session
When the checkpoint project-path resolver runs
Then it composes the project path with the worktree subdirectory into a single working path
And the heuristic engine runs branch detection against the worktree, not the repo root
```

#### UC-CP9: Uncommitted no-action changes still flag a commit

```gherkin
Given the only turn-local changes are bare no-action files (*.md, *.txt, *.rst outside docs/**) and none are categorized as code
And those changes have not been committed this turn
When the heuristic engine evaluates the turn window
Then a checkpoint is produced (not skipped)
And it includes the `telec code commit` instruction so the uncommitted change is not silently dropped

Given the only turn-local changes are bare no-action files
And they were already committed this turn (commit evidence follows the last mutation)
When the heuristic engine evaluates the turn window
Then no checkpoint is produced
```

#### UC-CP10: telec sync validation category for agents/commands/docs

```gherkin
Given the turn-local changes touch agents/** or agents/commands/** or docs/**
And no `telec sync` evidence appears in the checkpoint-cycle tool call timeline
When the heuristic engine evaluates the turn window
Then the result includes a required `telec sync` validation action
(The docs watcher deploys with `telec sync --skip-validation`, so an explicit
`telec sync` is the only validation pass for these paths.)

Given the turn-local changes touch agents/** or agents/commands/** or docs/**
And `telec sync` evidence appears in the checkpoint-cycle tool call timeline
When the heuristic engine evaluates the turn window
Then the `telec sync` validation action is suppressed

Given the turn-local changes touch agents/** (agent artifacts) and also require telec sync
When the heuristic engine evaluates the turn window
Then both the agent-artifacts restart-self action and the telec-sync validation action are surfaced, each once, in category precedence order

Given the session is on a worktree branch (not main)
And the turn-local changes touch docs/** or agents/commands/** (syncable sources, a main_only category) alongside agents/** (agent artifacts)
When the heuristic engine evaluates the turn window
Then the telec-sync validation action is omitted, because main_only work is deferred to integration on main
And syncable sources still appears in the changed-category summary, because the turn touched it
And the agent-artifacts restart-self action still surfaces
(The changed-category summary is a raw report of every category the turn touched; it never implies an action. A category whose action is deferred off-main or already satisfied still appears in the summary but drives no required action.)

Given the turn-local changes touch a code category with no per-category action (e.g. teleclaude/hooks/**, which auto-applies on next invocation) and no `telec sync`/restart obligation
And no log-check or test evidence appears in the timeline yet
When the heuristic engine evaluates the turn window
Then the category appears in the changed-category summary and the log-check and test actions it drives are surfaced

Given the same code category change
And the log-check and test evidence both appear in the timeline
When the heuristic engine evaluates the turn window
Then the category still appears in the changed-category summary and no action is surfaced for it, because its evidence was observed
(The changed-category summary reports the raw turn-local category set, independent of whether any action is surfaced. Actions are attributed separately, so a category may appear in the summary with no corresponding action when its action is satisfied or deferred.)
```

#### UC-CP11: Integrator post-merge maintenance force-fire

```gherkin
Given a session whose role is integrator
And the integration state machine advanced repo-root main this turn and recorded the integrator-maintenance marker carrying the delivered merge range
When the heuristic engine evaluates the turn window
Then the checkpoint force-fires even though no turn-local Edit/Write changes exist
And effective files are sourced from the merge delta over the recorded range
And only the main-only maintenance actions implied by that delta are surfaced (make install / uv sync / make restart / telec sync)
And no post-commit review action, no commit reminder, and no test or log-check actions are surfaced
And the integrator-maintenance marker is consumed

Given a session whose role is NOT integrator
And repo-root main advanced this turn for any reason
And no integrator-maintenance marker is present for this session
When the heuristic engine evaluates the turn window
Then no maintenance checkpoint is force-fired on account of the moved main HEAD
(Repo-root main is a shared working copy; raw HEAD movement is not
self-attributable, so only the lease-guarded integrator singleton — the recorded
marker's owner — receives post-merge maintenance.)
```

#### UC-CP12: Committed code surfaces discharging maintenance obligations

```gherkin
Given a session commits daemon code through the sealed `telec code commit` path this turn
And the commit handler categorizes the committed pathspec and records the owed main_only maintenance obligations (make install / uv sync / make restart / telec sync) into the commit-obligation ledger
And `git diff HEAD` is now empty because the commit moved HEAD
When the heuristic engine evaluates the turn window
Then the outstanding obligations are unioned into the turn's effective actions before the no-change early-exit
And the engine surfaces the maintenance actions those obligations imply (Run `make restart`)
And, on main with code committed, the post-commit review-gate action is surfaced in addition (per UC-CP5A)
And the test and log-check actions are NOT recorded as commit obligations — they remain cycle-local advisories on the dirty tree only
And the unsatisfied obligation persists into later checkpoint cycles until its evidence is observed or user-prompt-submit clears the ledger

Given a turn recorded a make-restart obligation and surfaced it
And the agent then runs `make restart` in the same turn
When the next agent-stop evaluates the turn window
Then the make-restart evidence in the timeline discharges the obligation, removing it from the ledger
And no make-restart action is surfaced
And the obligation does not reappear in any subsequent cycle of this turn

Given a turn recorded a telec-sync obligation and surfaced it in an earlier checkpoint cycle with no evidence
And the agent runs a full `telec sync` in a later cycle in response to that surfaced action
When the agent-stop for that later cycle evaluates the turn window
Then the telec-sync evidence discharges the obligation, removing it from the ledger
And a following zero-change cycle surfaces no telec-sync action
And fires no checkpoint on account of the committed file

Given a session commits a file the agent did not itself Edit or Write this turn (a human-staged change the agent committed on request)
When the heuristic engine evaluates the turn window
Then that committed file's maintenance obligations are still recorded from the commit
And its implied maintenance action is surfaced
(The commit is the agent action that attributes the file to the turn; timeline mutation signals are not required for committed files.)
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
When the heuristic engine evaluates the turn window
Then the file is categorized as daemon code
And the `make restart` obligation is recorded and surfaced
(Daemon-code categorization covers every daemon Python module at any depth under `teleclaude/`, top-level files included — not only nested ones.)

Given a session commits a CLI module the daemon imports at load (e.g. `teleclaude/cli/telec/surface.py`, held by `teleclaude/core/tool_access.py`)
When the heuristic engine evaluates the turn window
Then the file is categorized as daemon code
And the `make restart` obligation is recorded and surfaced
(A CLI module the daemon imports at startup changes daemon runtime behavior, so the daemon-code category includes it despite the general CLI-subprocess exclusion.)

Given a session commits a CLI module that runs only as a per-invocation subprocess and is not imported by the daemon
When the heuristic engine evaluates the turn window
Then the file is not categorized as daemon code
And no `make restart` obligation is surfaced for it
(The boundary is daemon-import membership, not directory: only CLI modules the daemon holds at runtime require a restart.)
```

#### UC-CP15: Committed-and-satisfied doc/no-action turn fires no checkpoint

```gherkin
Given the only turn-local changes are docs/** files (or there are no turn-local changes at all)
And those changes are committed this turn so nothing is left to commit
And every category obligation they imply is satisfied (e.g. `telec sync` evidence follows the last mutation, leaving no required actions and no observations)
And the turn did not author a code commit on main (no post-commit review gate)
When the heuristic engine evaluates the turn window
Then no checkpoint is produced
(A doc/no-action turn the engine has nothing left to act on is silently skipped, rather than rendered as the misleading "No code changes detected this turn." — doc changes were in fact made, committed, and synced.)

Given the only turn-local changes are docs/** files committed this turn
And no `telec sync` evidence appears in the checkpoint-cycle tool call timeline
When the heuristic engine evaluates the turn window
Then a checkpoint is produced surfacing the `telec sync` validation action (per UC-CP10), because the doc turn is not yet satisfied
```

### Cross-context references

- Belongs to `agent_runtime` in the v2 fold; inventoried in v1 alongside
  the receiver it composes with.
- Reads session row state owned by `agent_runtime`: last user message
  timestamp, last checkpoint timestamp, native log file, working
  subdirectory, project path, turn anchor SHA, working slug,
  native session id, and `system_role` (e.g. `"integrator"`) — the role
  is passed to `get_checkpoint_content` and stored in `CheckpointContext`
  to gate the integrator-maintenance force-fire path.
- Consumes the commit-obligation ledger written by the sealed `telec code commit`
  path for any session, and the integrator-maintenance marker written by the
  integration state machine (`project/spec/feature/workflow/integration-state-machine`)
  at delivery, before the per-candidate `pre_merge_head` is cleared.
- Writes checkpoint-seen entries that `session-state-mutation-via-outbox`
  consumes to update last-checkpoint timestamp.

## Known caveats

- Session-scoped flag markers live in a per-session temporary directory;
  session ids that contain unsafe characters are hashed to a digest
  component for the filesystem path.
- The clear flag is turn-scoped: it skips checkpoints for the current turn
  and is hard-cleared at the next non-system user-prompt-submit, alongside
  the commit-obligation ledger. A checkpoint that recurs across turns is a
  signal that the heuristics are over-tight — the agent surfaces it to the
  human rather than re-setting the flag. The recheck loop-guard is the
  involuntary backstop against an evidence-miss spinning forever.
- The commit-obligation ledger carries outstanding `main_only` maintenance
  actions derived from every sealed `telec code commit` in the turn (appended
  across commits, deduped on read). The engine unions them into the turn's
  effective actions so a commit does not empty the action ledger; per-action
  evidence discharges each obligation once its command runs. The ledger is
  hard-cleared at the next user-prompt-submit. Raw `git commit` outside the
  sealed path does not record it.
- The main-branch post-commit review gate is driven by a session-scoped
  authored-main-commit latch recorded by `telec code commit` only for
  commits whose pathspec includes code, then consumed when the review
  action surfaces. The latch triggers only the review gate — never the
  action or evidence ledger. It is not SHA-keyed, so rebases and peer HEAD
  movement do not re-arm it; doc-only commits do not arm it; raw
  `git commit` does not mark authorship.
- The integrator's raw-git merge does not flow through `telec code commit`
  and so does not arm the authorship latch or the commit-obligation ledger;
  instead the integration state machine records the integrator-maintenance
  marker carrying the delivered merge range, which the engine consumes to
  force-fire post-merge maintenance for the integrator session.
- Heuristics are zero-LLM and deterministic — pattern matching on
  version-control state and the transcript, no API calls.
- The engine is project-aware: it may short-circuit early for projects
  outside the supported set (the engine's project-allowlist policy
  lives in the engine itself).
- Worktree-aware path resolution composes the project path with the
  worktree subdirectory so branch detection runs against the working
  tree, not the repo root. Worktree sessions on a non-main branch
  behave correctly; sessions on main get the main-only category
  instructions (setup, deps, restart) suppressed unless they are the
  integrator receiving post-merge maintenance.
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
