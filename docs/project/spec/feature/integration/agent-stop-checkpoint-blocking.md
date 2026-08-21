---
description: 'Heuristic checkpoint engine that may block an agent_stop hook with an adapter-formatted instruction nudging the agent to commit, run tests, fix lint, run telec sync, or surface post-merge maintenance to the integrator.'
visibility: 'public'
---

# Agent Stop Checkpoint Blocking — Spec


## What it is

A deterministic, zero-LLM heuristic engine invoked from the hook receiver
on agent-stop events. It reads the current turn's transcript, the working
tree's version-control state scoped to the turn window, and a session's
project context, then classifies changed files into categories (code,
tests, docs, configs, infra, sync-validation) and produces a checkpoint
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
a **commit-obligation ledger**, carrying outstanding `main_only` maintenance
actions derived from every sealed `telec code commit` in the turn, sources
those actions into the action ledger so committing does not empty it; each
obligation discharges when its evidence is observed, and the ledger is
hard-cleared at user-prompt-submit; a fixed-name **authored main commit
marker** is recorded when this session commits **code** on `main` through
the sealed `telec code commit` path and triggers only the post-commit
review gate. The review gate defers while the working tree still carries an
uncommitted change owing a commit, so the marker persists across those turns
rather than being consumed; it surfaces once on a turn with no pending commit
and is consumed then, or is consumed when the review is dispatched. A
force-fire that has nothing left to surface — no changed files, no required
actions, no observations, and no commit action — produces no checkpoint. An
**integrator-maintenance marker**, carrying the delivered merge range and the
`main_only` maintenance actions that range owes, is recorded by the
integration state machine when it advances repo-root `main`. It is keyed to
the canonical checkout rather than to a session, because the state it records
— repo-root `main` advanced and the daemon deployed from this checkout has
not caught up — belongs to the checkout and outlives any one integrator.
Each recorded action discharges when its evidence is observed in any
checkpoint cycle, and the marker is removed once the last one discharges.


<!-- planned:govern-standalone-authored-content-review -->
The commit-obligation ledger also carries the `governed-content-review` action
when a sealed main-branch commit matches the platform-universal standalone
authored-content scope. Integrator maintenance never surfaces review actions
from its merge delta.
<!-- /planned:govern-standalone-authored-content-review -->

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
And that action instructs the authoring session to dispatch the commit(s) to independent review automatically
And waits for REVIEW COMPLETE before reporting completion
And routes a REQUEST CHANGES verdict through the author-owned remediation contract in `software-development/policy/commits`
And the authored-main-commit marker is consumed
(The authored-main-commit marker triggers only the review gate; commit-derived maintenance flows through the commit-obligation ledger — see UC-CP12.)

<!-- planned-change:govern-standalone-authored-content-review -->
Given the current branch is main
And this session authored a main commit through the sealed `telec code commit` path
And the committed pathspec contained only documentation (docs/**, *.md, *.txt, *.rst) with no code
When the commit gate runs
Then the authored-main-commit marker is NOT armed
And the next agent-stop produces no post-commit review-gate surfacing action for that commit
(Under doc-first, documentation is reviewed in the lifecycle, not at the post-commit review gate.)
<!-- change:govern-standalone-authored-content-review -->
Given the current branch is main
And this session authored a main commit through the sealed `telec code commit` path
And the committed pathspec contains only documentation snippets or agent artifacts
And it contains neither code nor standalone authored descriptive content
When the commit gate runs
Then the authored-main-commit marker is NOT armed
And the next agent-stop produces no code-authorship post-commit review action for that commit
And the existing snippet or agent-artifact review route remains unchanged
<!-- /planned-change:govern-standalone-authored-content-review -->

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
And this turn's tool timeline contains a review dispatch for the commit(s) — a `telec sessions run --command /next-review-commits ...` run, or a remediation `telec sessions send <reviewer> "review commits ..."` whose message payload begins with "review commits"
When the heuristic engine evaluates the turn window
Then the post-commit review-gate surfacing action is NOT emitted
And the authored-main-commit marker is consumed
And when no changed files, required actions, observations, or commit action remain, no checkpoint is produced rather than an empty "No code changes detected this turn." block
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
(An explicit `telec sync` is the agent's validation pass for these paths.)

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
And the telec-sync category is omitted from the changed-category summary
And the agent-artifacts restart-self action still surfaces
(The changed-category summary reports only branch-eligible actions; an off-main deferral is emitted as a separate affirmative decision record.)

Given the turn-local changes touch a code category with no per-category action (e.g. teleclaude/hooks/**, which auto-applies on next invocation) and no `telec sync`/restart obligation
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

#### UC-CP11: Integrator post-merge maintenance force-fire

```gherkin
Given a session whose role is integrator
And the integration state machine advanced repo-root main this turn and recorded the integrator-maintenance marker carrying the delivered merge range
When the heuristic engine evaluates the turn window
Then the checkpoint force-fires even though no turn-local Edit/Write changes exist
And effective files are sourced from the merge delta over the recorded range
And only the main-only maintenance actions implied by that delta are surfaced (make install / uv sync / make restart / telec sync)
And no post-commit review action, no commit reminder, and no test or log-check actions are surfaced
And every surfaced action remains recorded on the integrator-maintenance marker

Given a session whose role is NOT integrator
And repo-root main advanced this turn for any reason
And no integrator-maintenance marker is present for this checkout
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

<!-- planned:govern-standalone-authored-content-review -->
Given a session commits standalone authored descriptive content through the sealed `telec code commit` path on main
When the commit handler categorizes the committed pathspec
Then the `governed-content-review` action is recorded in the commit-obligation ledger
And a mixed code-and-content commit retains the code-authorship marker and the governed-content obligation
And the heuristic engine renders their shared independent-review instruction once
And review-dispatch evidence discharges both routes
<!-- /planned:govern-standalone-authored-content-review -->

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

#### UC-CP16: Descriptor-only shell redirects do not surface a checkpoint

```gherkin
Given a turn's only shell command is read-only (e.g. `grep`, `git show`) and redirects a file descriptor to a non-file sink (e.g. `2>/dev/null`, `2>&1`)
And the working tree carries a pre-existing dirty file unrelated to this turn
When the heuristic engine evaluates the turn window
Then the descriptor redirect is not classified as file-mutating intent
And the pre-existing dirty file is not attributed to this turn
And no checkpoint is produced
(A descriptor redirect that suppresses or duplicates a stream is not a file write; classifying it as one reattributes stale dirty state to a turn that made no changes.)

Given a turn's only shell command redirects a numbered file descriptor to a real file path (e.g. `2>teleclaude/core/tracked.py`)
When the heuristic engine evaluates the turn window
Then the redirect is classified as file-mutating intent
And a checkpoint is produced
(The exemption is scoped to non-file sinks, never to the presence of a descriptor number; a numbered descriptor writing to a real path is still a file write.)
```

#### UC-CP17: A sealed commit outside the deployed source records no maintenance obligation

```gherkin
Given a session commits daemon code through the sealed `telec code commit` path from a slug worktree
When the commit handler categorizes the committed pathspec
Then no main_only maintenance obligation is recorded into the commit-obligation ledger
And a later agent-stop cycle for that session surfaces no `make restart` action, even when the session's own working path is the main checkout
(The commit's own location decides what maintenance it owes; the location of the session that issued it does not. A commit from the main checkout records its obligations per UC-CP12.)
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


#### UC-CP20: Post-merge maintenance persists per action until its evidence is observed

```gherkin
Given the integration state machine confirms a delivery whose merge delta owes make restart and telec sync
When it records the integrator-maintenance marker for this checkout
Then the range and both owed main-only action ids are recorded together
(The owed actions are resolved at delivery through the same merged model and single matcher every other consumer uses, so a delivered path owes the equivalent action in each of them.)

Given an integrator-maintenance marker for this checkout already owes telec sync
And a further candidate is delivered in the same drain whose delta owes make restart
When the state machine records that candidate's range
Then the marker's outstanding set is the union of both deliveries' owed actions

Given an integrator-maintenance marker recorded for this checkout owes make restart and telec sync
And an earlier checkpoint cycle surfaced both
And the agent ran make restart in that cycle and nothing since
When a later agent-stop evaluates the turn window
Then the make-restart action is discharged from the marker and is not surfaced again
And the telec-sync action is still surfaced
And the marker is retained
(Evidence is read from the checkpoint-cycle timeline, which carries only the current cycle. Discharge is therefore recorded on the marker as it is observed; re-deriving it from the timeline each cycle would lose every action satisfied in an earlier one.)

Given the marker's last outstanding action is discharged
When the agent-stop cycle that observes its evidence completes
Then the marker is removed
And no post-merge maintenance checkpoint force-fires for that delivery again

Given an integrator-maintenance marker recorded for this checkout still owes make restart
And the integrator session that incurred it has ended
And a different integrator session acquires the lease on the same checkout
When the heuristic engine evaluates that session's turn window
Then the outstanding make-restart action is surfaced to the successor
(The obligation describes the checkout and the daemon deployed from it, so it is addressed by the checkout and reaches whichever integrator holds the lease.)
```


<!-- planned:govern-standalone-authored-content-review -->
#### UC-CP20: Standalone authored content receives governed-content review

```gherkin
Given an agent authors standalone descriptive content such as a README, CHANGELOG, CONTRIBUTING guide, SECURITY guide, release note, or descriptive sample configuration
And the content is neither a documentation snippet nor an agent artifact
When the agent records the change on main
Then the checkpoint requires one independent governed-content review
And the reviewer applies the documentation lane to accuracy and currency and the security lane to repository privacy
And the authoring session waits for REVIEW COMPLETE without surfacing technical review decisions to the human
```
<!-- /planned:govern-standalone-authored-content-review -->

<!-- planned:govern-standalone-authored-content-review -->
#### UC-CP21: Generated and externally owned content remains review-exempt

```gherkin
Given a committed text surface is generated output, vendored material, or unchanged third-party content
When the checkpoint classifies post-commit review obligations
Then no governed-content review is required for that surface
```
<!-- /planned:govern-standalone-authored-content-review -->

<!-- planned:govern-standalone-authored-content-review -->
#### UC-CP22: Existing governed surfaces keep their own lanes

```gherkin
Given a commit changes standalone authored content together with a documentation snippet, directive text, or an agent artifact
When post-commit review is routed
Then one independent reviewer applies every triggered lane to the mixed commit
And documentation snippets and directive text remain in doc-hygiene
And project and global agent master artifacts remain in the agent-artifact review path
And standalone authored descriptive content is reviewed only through governed-content mode of the documentation lane
```
<!-- /planned:govern-standalone-authored-content-review -->

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
  identifiers that contain unsafe characters are hashed to a digest
  component for the filesystem path. The integrator-maintenance marker is
  the one exception: it is addressed by the canonical checkout, so it lives
  under a checkout-derived component and is reachable by every session
  working from that checkout.


- The clear flag is turn-scoped: it skips checkpoints for the current turn
  and is hard-cleared at the next non-system user-prompt-submit, alongside
  the commit-obligation ledger. A checkpoint that recurs across turns is a
  signal that the heuristics are over-tight — the agent surfaces it to the
  human rather than re-setting the flag. The recheck loop-guard is the
  involuntary backstop against an evidence-miss spinning forever.
<!-- planned-change:govern-standalone-authored-content-review -->
- The commit-obligation ledger carries outstanding `main_only` maintenance
  actions derived from every sealed `telec code commit` in the turn (appended
  across commits, deduped on read). The engine unions them into the turn's
  effective actions so a commit does not empty the action ledger; per-action
  evidence discharges each obligation once its command runs. The ledger is
  hard-cleared at the next user-prompt-submit. Raw `git commit` outside the
  sealed path does not record it.
<!-- change:govern-standalone-authored-content-review -->
- The commit-obligation ledger carries outstanding `main_only` actions derived
  from every sealed `telec code commit` in the turn, including structurally
  triggered governed-content review alongside maintenance (appended across
  commits, deduped on read). The engine unions them into the turn's effective
  actions so a commit does not empty the action ledger; per-action evidence
  discharges each obligation once its command runs. The ledger is hard-cleared
  at the next user-prompt-submit. Raw `git commit` outside the sealed path does
  not record it. Integrator maintenance consumes only maintenance actions from
  its merge delta and never surfaces review actions.
<!-- /planned-change:govern-standalone-authored-content-review -->
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
  marker carrying the delivered merge range and the actions it owes, which
  the engine reads to force-fire post-merge maintenance for the integrator
  session holding the lease on that checkout.


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
- docs/project/adr/0070-clean-working-tree-floors-the-commit-action-checkpoint.md
