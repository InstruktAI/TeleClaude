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

The engine is gated by session-scoped flag markers: a persistent **clear
flag** disables checkpoints for the session entirely; turn scoping
prevents ordinary file-change checkpoints from re-firing after a
checkpoint has been delivered; a fixed-name **authored main commit
marker** is recorded when this session commits **code** on `main` through
the sealed `telec code commit` path, then consumed when the post-commit
review action is surfaced; and an **integrator-maintenance marker**,
carrying the delivered merge range, is recorded by the integration state
machine when it advances repo-root `main`, then consumed when the
integrator's post-merge maintenance checkpoint is surfaced.

## Canonical fields

### Use cases

#### UC-CP1: Uncommitted code changes block stop

```gherkin
Given a Claude session has modified source files in the current turn
And no commit has been recorded since the last mutation
And the persistent clear flag is not set
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

#### UC-CP2: Persistent clear flag skips checkpoint

```gherkin
Given the session-scoped checkpoint clear flag is set
When the checkpoint pre-emit step runs
Then the per-turn recheck flag is cleared so a future re-enable can re-arm checkpoints cleanly
And a "checkpoint skipped (persistent clear flag)" info log emits
And the checkpoint pre-emit returns no decision
And the receiver enqueues the agent-stop event normally without emitting a block response
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

#### UC-CP5: Per-turn recheck flag cleared on new user prompt

```gherkin
Given a checkpoint fired earlier in this turn and set the per-turn recheck flag
When a new user-prompt-submit hook arrives that is NOT system-injected
Then the per-turn recheck flag is consumed
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

Given the current branch is main
And this session authored a main commit through the sealed `telec code commit` path
And the committed pathspec contained only documentation (docs/**, *.md, *.txt, *.rst) with no code
When the commit gate runs
Then the authored-main-commit marker is NOT armed
And the next agent-stop produces no post-commit review-gate surfacing action for that commit
(Under doc-first, documentation is reviewed in the lifecycle, not at the post-commit review gate.)

Given the current branch is main
And HEAD moved because of a peer commit, `git pull --rebase`, merge, or other commit not authored by this session
And the session-scoped authored-main-commit marker is absent
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
And no system role, including integrator, is exempt from this code-authorship rule
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

### Cross-context references

- Belongs (along with the receiver) to `agent_runtime` in the v2 fold,
  since checkpoint blocking is a property of agent-CLI orchestration,
  not of external integration. Inventoried here in v1 because it
  composes with the receiver.
- Reads session row state owned by `agent_runtime`: last user message
  timestamp, last checkpoint timestamp, native log file, working
  subdirectory, project path, turn anchor SHA, working slug,
  native session id, and `system_role` (e.g. `"integrator"`) — the role
  is passed to `get_checkpoint_content` and stored in `CheckpointContext`
  to gate the integrator-maintenance force-fire path.
- Consumes the integrator-maintenance marker written by the integration
  state machine (`project/spec/feature/workflow/integration-state-machine`)
  at delivery, before the per-candidate `pre_merge_head` is cleared.
- Writes checkpoint-seen entries that `session-state-mutation-via-outbox`
  consumes to update last-checkpoint timestamp.

## Known caveats

- Persistent flag markers live in a per-session temporary directory;
  session ids that contain unsafe characters are hashed to a digest
  component for the filesystem path.
- The clear flag persists across turns until explicitly removed; it is
  the user/operator's responsibility to delete it to re-enable
  checkpoints.
- The main-branch post-commit review gate is driven by a session-scoped
  authored-main-commit latch recorded by `telec code commit` only for
  commits whose pathspec includes code, then consumed when the review
  action surfaces. The latch is not SHA-keyed, so rebases and peer HEAD
  movement do not re-arm it; doc-only commits do not arm it; raw
  `git commit` does not mark authorship.
- The integrator's raw-git merge does not flow through `telec code commit`
  and so does not arm the authorship latch; instead the integration state
  machine records the integrator-maintenance marker carrying the delivered
  merge range, which the engine consumes to force-fire post-merge
  maintenance for the integrator session. This closes the former gap where
  integrator merges surfaced no maintenance.
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
