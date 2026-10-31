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

An Antigravity turn completion forwarded from a provider-native subagent's
idle `Stop` (`local/projects/teleclaude/spec/hook-normalized-events`) is
evaluated like every agent-stop event. A checkpoint it requires is never
answered on that hook, which receives the provider's plain success response;
it is relayed to the session's control delivery instead
(`local/projects/teleclaude/design/architecture/checkpoint-system`).

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
a turn-scoped **clear flag** skips checkpoints for the current turn and clears
the per-turn recheck latch so later re-enablement can work. The clear flag and
recheck latch are consumed at the next non-system user-prompt-submit; turn
scoping prevents ordinary file-change checkpoints from re-firing after a
checkpoint has been delivered;
a fixed-name **authored main commit
marker** is recorded when this session commits **code** on `main` through
the sealed `telec repo commit` path and triggers only the post-commit
review gate. The review gate defers while the working tree still carries an
uncommitted change owing a commit, so the marker persists across those turns
rather than being consumed; it surfaces once on a turn with no pending commit

and is consumed then, or is consumed when the review is dispatched or when a
commit-review stamp covers this session's commits. A force-fire that has
nothing left to surface — no changed files, no required actions, no
observations, and no commit action — produces no checkpoint.

An **integrator-maintenance marker** carries canonical-main activations whose
deterministic maintenance was recorded and whose live-runtime log judgment
remains. It is keyed to the canonical checkout rather than to a session, so a
successor integrator inherits unfinished judgment without repeating mechanical
work. The commit boundary records it for direct main commits and integration
advancements alike, after the owed action records are durable. It retains the
activation times and becomes eligible only after every owed action succeeds;
the executor records its latest maintenance-ready time. The integrator reads
logs after that time from a window beginning no later than the earliest
activation. Earlier or narrower log evidence cannot discharge the marker. A regular
committing session receives no maintenance log-check action from this project.

The action and evidence ledger — what needs doing and what was done since
the turn started — is time-anchored to the turn window and is
wholesale-cleared at user-prompt-submit.

On a shared branch, version control is consulted only as the category oracle
(which file maps to which category), never as the arbiter of what is in-scope
or done; declarations answer that. In a todo worktree, the checkpoint reads
the stopping session's lifecycle job and working slug from its session record.
The todo's builder and finalizer owe its dirty paths regardless of declarations;
other sessions in that todo worktree owe no commit action for those paths. The
checkpoint retains worktree-wide scope outside todo worktrees. The sealed
commit command's worktree scope remains task-wide.

On a shared branch, a session whose shell activity in the current checkpoint
cycle wrote a dirty path it has not declared is asked, by name, to declare that
path if it is its own. The question is advisory: it creates no obligation, no
declaration, and no commit action. When it is the only thing to say, the
checkpoint still produces a decision carrying it; the next checkpoint cycle
starts after that decision, so the same question is not repeated without new
shell activity writing the path. A path that shell activity only carries as
data, such as message text or the content of a file written elsewhere, is not
written by it and raises no question. Paths the session wrote through its edit
tools need no question; they are declared when the call succeeds.

Without a turn-start anchor, the stop is not blocked. If evaluation fails before
establishing a complete action set, it produces no block and does not mark the
cycle checked. A worktree session resolves path and branch scope against the
checkout named by its recorded worktree subdirectory. A sealed commit after the
last relevant edit satisfies the commit obligation for those changes. An
evaluation with no required action, no outstanding assessment, and nothing else
to surface — including no observations or advisory questions — emits no
checkpoint and records no checkpoint-seen entry.

## Canonical fields

### Use cases

#### UC-CP1: Uncommitted code changes block stop

#### UC-CP2: Turn-scoped clear flag skips checkpoint for the current turn

#### UC-CP3: No turn start → no checkpoint

#### UC-CP4: No turn-local changes → no checkpoint

#### UC-CP5: Turn-scoped markers cleared on new user prompt

#### UC-CP5A: Main-branch post-commit review action follows code authorship

```gherkin
Given the current branch is main
And this session authored a main commit through the sealed `telec repo commit` path
And the committed pathspec included code (not a doc-only commit)
And the session-scoped authored-main-commit marker is present
When the heuristic engine evaluates the turn window
Then the result includes the post-commit review-gate surfacing action
And that action names the commit(s) as review candidates and states that the authoring session decides whether each owes independent review by what the commit set out to do
And directs a commit through which the session wrote new or changed code or documentation content to an independent reviewer the session dispatches automatically, waiting for its verdict before reporting completion
And directs a commit through which the session wrote neither — a removal, a merge of already-reviewed work, a validation or other mechanical repair — to the author's discard, `telec repo stamp <sha> --verdict approve --reason <text>`
And routes a REQUEST CHANGES verdict through the author-owned remediation contract in `general/policy/commits`
And the authored-main-commit marker is consumed
(The authored-main-commit marker triggers only the review gate; owed maintenance is recorded and started at the commit boundary — see `local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`.)

Given the current branch is main
And this session authored a main commit through the sealed `telec repo commit` path
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
And this turn's tool timeline contains a review dispatch for the commit(s) — a `telec sessions run` run whose `--command` value names the commit-review command, or a `telec sessions send` addressed to a live commit-review session this session started, whatever its message
When the heuristic engine evaluates the turn window
Then the post-commit review-gate surfacing action is NOT emitted
And the authored-main-commit marker is consumed
And when no changed files, required actions, observations, or commit action remain, no checkpoint is produced rather than an empty "No code changes detected this turn." block
So the main-commit force-fire does not re-surface the review gate on a commit whose review was already dispatched
And a command that merely mentions the commit-review command without dispatching it (a different `--command`), or a `telec sessions send` addressed to any other session, does not discharge the gate
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

#### UC-CP8: Worktree subdir resolution for branch detection

#### UC-CP9: Recorded edits with pending commit evidence require the commit step

#### UC-CP10: Code categories with no per-category action

```gherkin
Given a regular session's turn-local changes touch a code category with no per-category action
And the changed paths owe this project's live-runtime log judgment
When the heuristic engine evaluates the turn on main or in a worktree
Then the maintenance log-check action is not surfaced to that session
And any distinct branch-eligible actions still follow their bindings and evidence
And categories for those eligible actions remain in the changed-category summary even after evidence satisfies them
```

#### UC-CP11: Integrator post-advance log-check force-fire

```gherkin
Given a session whose role is integrator
And a canonical-main advancement has a checkout-scoped marker for live-runtime judgment
And every action owed by that marker has succeeded with a maintenance-ready time recorded
When the heuristic engine evaluates the turn window
Then the checkpoint force-fires despite no turn-local Edit or Write change
And it surfaces the log-check action for the accumulated activations
And it instructs the integrator to publish any ahead canonical local main head after judging the owed logs sound
And other sessions' review state and unrelated uncommitted paths do not delay that push
And a material failure keeps that head local for recovery and a new log judgment
And no mechanical maintenance or unrelated judgment action is surfaced from that marker

Given an owed action is pending, failed, or interrupted, or no maintenance-ready time is recorded
When the heuristic engine evaluates that marker
Then it does not force-fire log judgment yet
And the marker remains for integrator recovery and a later eligible check
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
And a non-empty pending companion sibling `<stem>.<slug>.md` exists on disk
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
Given a session commits a top-level daemon module directly under `teleclaude/` (e.g. `teleclaude/constants.py`, `teleclaude/daemon.py`) through the sealed `telec repo commit` path
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

#### UC-CP20: Post-advance log judgment begins with a range-only marker

```gherkin
Given a canonical-main advancement whose paths owe live-runtime judgment
And its deterministic maintenance actions are durably recorded
When the commit boundary records the checkout-scoped marker
Then the marker carries that advancement and its activation time but no mechanical action id
And it remains ineligible for discharge until every owed action succeeds
```

#### UC-CP30: Post-delivery log markers accumulate ranges

```gherkin
Given another qualifying advancement occurs before integrator log judgment is discharged
When its range is recorded
Then the checkout-scoped marker accumulates both ranges and their activation times
And one later log read must cover the earliest activation through the latest completed maintenance
```

#### UC-CP31: Log evidence discharges the range marker

```gherkin
Given every action owed by the marker's accumulated advancements has succeeded
And the integrator reads logs after the latest maintenance completion with a window beginning no later than the earliest activation
When a later agent-stop observes that evidence
Then the marker is removed and no post-delivery checkpoint force-fires for those ranges again
But an earlier read or a narrower window leaves the marker outstanding
```

#### UC-CP32: A successor integrator inherits unfinished log judgment

```gherkin
Given the integrator session ends while the checkout-scoped marker remains
And another integrator acquires the lease for the same checkout
When the successor inspects the marker
Then it inherits the accumulated activations and any unfinished maintenance recovery
And the log-check obligation surfaces only after every owed action succeeds and maintenance readiness is recorded
```

#### UC-CP23: Worktree checkpoints omit live-runtime log checks

```gherkin
Given a regular agent session is working from a non-main todo worktree
And its turn-local changes match a scope that owes integrator live-runtime judgment
When the checkpoint engine evaluates the agent-stop boundary
Then the worktree checkpoint omits the live-runtime log-check action
And any other worktree-eligible actions remain unchanged

Given a regular agent session is working from canonical main
And its turn-local changes match the same scope
When the checkpoint engine evaluates the agent-stop boundary
Then the ordinary file-based checkpoint still omits the maintenance log-check action
And the checkout-scoped integrator marker retains that judgment for the standing integrator
```

#### UC-CP24: Actionless checkpoint evaluation is silent

#### UC-CP25: Checkpoint reasons use the hook-boundary control envelope

```gherkin
Given a Claude, Codex, or Gemini agent session reaches a checkpoint hook boundary
When TeleClaude delivers a non-empty checkpoint reason to that agent runtime
Then the reason is framed by the canonical XML checkpoint control envelope
And no bracket checkpoint envelope is emitted on the hook boundary
```

#### UC-CP28: Maintenance the commit boundary performs is not an agent obligation

```gherkin
Given a regular session commits daemon code on canonical main through the sealed commit path
And the committed paths owe deterministic maintenance and live-runtime judgment
When the checkpoint evaluates that session
Then it surfaces neither maintenance nor maintenance log-check to the committer
And the independent post-commit review action remains owed for the committed code
And the checkout-scoped integrator marker retains live-runtime judgment

Given the same turn also owes a distinct judgment action eligible for that session
When the checkpoint evaluates the turn
Then that distinct action remains eligible
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

#### UC-CP34: A todo worktree writer owes its dirty tree

#### UC-CP35: A reviewer in a todo worktree owes no commit for the builder's changes

#### UC-CP36: A shell write the session has not declared is put to it as a question

#### UC-CP37: A file written through an edit tool is already declared at the stop

#### UC-CP38: A retiring parent's edit owes its empty companion no mirror

```gherkin
Given a turn edits a live parent doc snippet `<stem>.md`
And an empty companion sibling `<stem>.<slug>.md` beside it marks the parent retired
And the companion is NOT in the turn's changed files
When the heuristic engine evaluates the turn window
Then the agent receives no companion-drift action for that parent
```

#### UC-CP39: A commit-review stamp discharges the post-commit review gate

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
- Consumes the checkout-scoped marker recorded at each qualifying canonical-main
  activation after its action records are durable. It surfaces integrator log
  judgment only after the executor records terminal success and the latest
  maintenance-ready time; an earlier or narrower read cannot discharge it.
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
  authored-main-commit latch recorded by `telec repo commit` only for
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

- docs/local/adr/0037-checkpoint-ledger-separates-commit-detection.md
- docs/local/adr/0038-companion-drift-caught-at-checkpoint.md
- docs/local/adr/0070-clean-working-tree-floors-the-commit-action-checkpoint.md
- docs/local/adr/0086-checkpoint-failures-do-not-invent-work.md
