---
description: Deterministic maintenance runs automatically at the commit boundary,
  for every committer, performing the actions a commit's changed paths owe and reporting
  each through the structured logging boundary.
visibility: internal
---

# Post-Commit Maintenance — Spec

## What it is

A canonical-main activation range's changed paths owe a set of deterministic
maintenance actions — the actions the merged registry declares, such as
installing the checkout's toolchain and running the documentation and artifact
pipeline. Those actions carry no decision: each either ran or it did not.

Maintenance runs automatically whenever the canonical checkout advances: the
post-commit hook carries a commit recorded there, while the post-merge hook
carries the complete `ORIG_HEAD..HEAD` range activated by either a merge commit
or a fast-forward. It is not addressed to a session and does not depend on one
existing, so a person committing by hand and an integrator delivery receive the
same maintenance.

The owed set is resolved by the shared scope matcher from the merged registry
pair and bindings (`local/projects/teleclaude/design/architecture/checkpoint-system`, Invariant
25). This surface consumes the maintenance registry and recreates no location
rule or second table of paths, actions, or commands.

Which hooks a project has installed, and when they are installed, belongs to
`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`. This
contract governs only what happens when maintenance runs.

## Canonical fields

- **Trigger.** A recorded commit on canonical main, or a successful canonical-main
  merge operation, including a fast-forward. Maintenance is not conditioned on
  who or what advanced main, nor on whether a session is present.
- **Immutable activation range.** Hook ingress resolves symbolic Git names to
  object ids before action selection or logging. An ordinary commit records its
  parent and committed tip; a root commit records an absent parent and its tip;
  a merge or fast-forward records the resolved pre-activation and post-activation
  tips. Changed-file resolution, command expansion, outcomes, and replay all use
  those immutable fields.

<!-- planned-change:commit-maintenance-sheds-platform-work -->

- **Owed set.** The main-only maintenance actions selected by the merged
  registry's path bindings and canonical-main activation bindings. An
  activation binding applies even when the commit changes no paths. The shared
  matcher owns this selection under
  `local/projects/teleclaude/design/architecture/checkpoint-system`. Actions run
  in declared precedence waves, where a precedence orders an action after the
  actions whose effects it needs and after nothing else; a failure does not
  cancel later waves. An owed restart action is not a wave: it is the
  stopped-daemon window the other owed actions run inside, except the actions
  the registry declares to run while the daemon serves — Blueprint maintenance,
  publication and configuration-schema publication — which run after the
  window's verified start.

<!-- change:commit-maintenance-sheds-platform-work -->

- **Owed set.** The main-only maintenance actions selected by the merged
  registry's path bindings and canonical-main activation bindings. An
  activation binding applies even when the commit changes no paths. The shared
  matcher owns this selection under
  `local/projects/teleclaude/design/architecture/checkpoint-system`. Actions run
  in declared precedence waves, where a precedence orders an action after the
  actions whose effects it needs and after nothing else; a failure does not
  cancel later waves. No owed action stops, starts or replaces the daemon: a
  commit changes nothing live, and the install act is the only path to the
  live platform (`local/projects/teleclaude/design/architecture/installation`).

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

- **Recording outcome.** The activation boundary distinguishes an owed set
  durably recorded, an explicitly empty owed set, and a refused activation with
  its reason. Repeating an already-recorded owed set remains a recorded outcome.
  Ineligible location, an invalid immutable range, unavailable Git state and a
  storage failure are not evidence of an empty owed set or completed recording.
  Consumers use that outcome rather than inferring success from absent action
  files. The immutable-range and source-preservation requirements follow
  `sdlc/policy/version-control-safety`.

- **Blueprint.** In code-enabled projects, every canonical-main activation
  owes the Blueprint action. Its committed snapshot, current-query guarantee,
  and recovery are owned by `sdlc/spec/codebase-blueprint` and realized by
  `local/projects/teleclaude/spec/feature/workflow/blueprint-freshness`.

- **Location.** Maintenance performs the owed `main_only` actions from canonical
  main. A detached development clone, an integration worktree and an
  installation's release gain no eligibility; the integration worktree can
  create a delivery, but its commits and merges perform no maintenance.

- **Reporting.** Every attempt and every outcome is emitted through the
  structured logging boundary, carrying the commit, the resolved action set,
  and each action's result. The record, not an inference over a transcript, is
  what establishes whether maintenance ran. A failed action is reported at error
  level with the tail of its own combined output, so the reason it gave travels
  with its result; an action that succeeds keeps its output to itself. The
  whole output is masked before its tail is taken: every value the
  configuration declares sensitive (a field marked sensitive in the machine,
  global, project, person or company configuration, or a company service
  credential) is replaced, whatever its length, and every other value stays
  readable. A value an action obtains from anywhere else is not declared a
  secret and is not masked. When that configuration does not load, the
  secrets are unknown and the output is withheld, naming why. On-demand
  maintenance captures nothing: its actions write to the terminal of whoever
  ran it.
- **Failure posture.** The commit is already recorded before maintenance
  begins. A failing action is reported and the remaining actions still run;
  no failure withdraws, amends, or blocks the commit.

- **Committed source.** A publication action is selected by its recorded range
  and consumes the committed-source selection owned by
  `local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`:
  canonical-main publication reads the committed main tip. Every other
  repository remains at its previously activated revision until its own
  maintenance or `telec sync` runs. Working-tree files are never inputs.

- **Recovery.** A failed action is replayed through this executor for its
  original recorded range and action id, with the same attempt and outcome
  records as the first run. Publication uses the current committed source
  selected for that checkout, never its working tree or a different checkout's
  branch. Where no action was recorded, or maintenance did not run or left a root
  unconverged, `telec sync` in the affected root performs that root's maintenance
  on demand through this executor
  (`local/projects/teleclaude/spec/feature/integration/on-demand-maintenance`).

- **Absence.** A commit made where the hook is not installed performs no
  maintenance and raises no signal. Nothing detects that absence here:
  installed plumbing is machine state whose comparison against the project's
  declaration is already owned by project plumbing convergence, and a second
  detector would make this contract a second owner of that state.

- **Quick-return activation.** After resolving an immutable activation and its
  owed action set, the hook records each owed action durably, starts a one-shot
  drain contender, and returns without waiting for action completion. A later
  commit adds its own owed records while an earlier drain is running.
  A successful post-merge handoff prints a concise terminal notice that automatic
  maintenance has started in the background, may take some time, and needs no
  manual installation. No start notice is printed when no work is owed or the
  background process could not be started.
- **Per-action state.** Each gitignored record is keyed by the activated tip
  and action id and retains the pre-activation revision and queued time. A
  confirmed success removes its record. A terminal failure remains marked
  failed, with its exit code and the tail of its output, for structured-log and
  anomaly review, without an automatic retry loop.
  An interrupted attempt remains eligible for retry; each action converges
  safely when repeated after its effect preceded record removal.

<!-- planned-change:commit-maintenance-sheds-platform-work -->

- **Settlement announcement.** A commit activation of the canonical checkout
  is settled once every action it owes has a terminal outcome: success, or a
  failure that stays recorded; an activation that owes no action settles when
  it is registered. A restart obligation whose window start verified counts as
  succeeded, even while the window keeps it beside an action that failed inside
  that window. Settling announces the activation's state as an
  event of the `teleclaude.maintenance.activation` family in the checkout's
  project, with the activated tip as its subject: `failed` when any owed
  action failed terminally, naming each failed action with the command that
  replays it, otherwise `succeeded`. A replay that completes the
  failed actions settles the activation again and announces `succeeded` for the
  same subject. Every settled activation's announcement stays held until it is
  published, and holding a later one never drops an earlier one. An activation
  that settles while no daemon serves is announced once one does. A repeated
  announcement of one settlement carries the same event id, and settlements of
  different projects never share one. Event activations are not announced.

<!-- change:commit-maintenance-sheds-platform-work -->

- **Settlement announcement.** A commit activation of the canonical checkout
  is settled once every action it owes has a terminal outcome: success, or a
  failure that stays recorded; an activation that owes no action settles when
  it is registered. Settling announces the activation's state as an
  event of the `teleclaude.maintenance.activation` family in the checkout's
  project, with the activated tip as its subject: `failed` when any owed
  action failed terminally, naming each failed action with the command that
  replays it, otherwise `succeeded`. A replay that completes the
  failed actions settles the activation again and announces `succeeded` for the
  same subject. Every settled activation's announcement stays held until it is
  published, and holding a later one never drops an earlier one. An activation
  that settles while no daemon serves is announced once one does. A repeated
  announcement of one settlement carries the same event id, and settlements of
  different projects never share one. Event activations are not announced.

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

- **One-shot drain.** Every hook that records owed work starts a contender. One OS-owned file lock
  admits a single active drain; contenders wait for that lock, process pending
  activations in Git ancestry order and actions by declared precedence, then
  exit when no pending work remains. Lock-file presence never means ownership.

- **On-demand runs.** An on-demand run holds the same lock for its whole run, so
  a drain and an on-demand run never perform a step at the same time. Its
  attempts and outcomes are marked as on-demand in the structured records. A
  drain never executes an on-demand run's steps, and an on-demand run never
  executes, replaces or clears a recorded activation's actions; it reads a
  terminal failure only to name it with its replay.

- **Execution.** No maintenance action and no drain contender goes through the
  `telec` command surface. An action that runs TeleClaude's own code runs a
  module entrypoint of the installed checkout under the interpreter of the
  draining process, and the hook starts the drain contender the same way, so
  maintenance depends on no caller identity and on no command existing. A
  failed action is replayed with `telec repo maintenance retry`, which re-runs
  the recorded action through this executor.

- **Event activations.** The executor also performs the actions a project's
  event bindings owe for one event
  (`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`).
  An event activation is identified by its event and the project, carries no
  activation range, and keeps the event it reacts to for as long as any of its
  action records remains. Its records sit beside the commit activations' records
  under the same drain lock, a drain takes event activations in the order they
  were recorded, and its attempts and outcomes are marked as event activations
  in the structured records. A failed event action is replayed with
  `telec repo maintenance retry` for its original event activation, and
  `telec repo maintenance status` names each event activation with that replay.
  An event activation records no integrator judgment: the maintenance an advance
  of canonical main owes is that advance's own activation.

<!-- planned-change:commit-maintenance-sheds-platform-work -->

- **Replacement owed.** In a root whose registry declares the restart action,
  every activation whose changed paths select any maintenance action other than
  one the registry declares to run while the daemon serves owes the restart
  action, whatever its bindings name. An activation whose changed paths select
  only such actions — publication among them — or nothing, a
  documentation-only change among them, owes no restart and runs, together
  with the actions every canonical-main activation owes, while the daemon keeps
  serving. A root that declares no restart action has no window.

- **Stopped-daemon window.** An activation whose owed set includes the
  restart action replaces the daemon inside a stopped-daemon window, a
  controlled restart under `local/projects/teleclaude/policy/daemon-availability`.
  The window opens before any of the activation's owed actions that run inside
  it. It first waits, admission still open, until the daemon holds no accepted work,
  up to a bound the window owns; an integration whose commit owes the restart
  is accepted work like any other, so its own window never closes admission
  while it is still running. It then stops the daemon through `make stop`,
  whose preparation settles the work accepted until then
  (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).
  A preparation that does not complete within its observation window is
  reported, and the window keeps waiting and stopping again until the daemon
  has stopped; no owed action runs while the daemon serves. With the daemon
  stopped, every owed action that runs inside the window runs in its
  precedence waves; installation inside the window leaves the tmux server running
  (`local/projects/teleclaude/policy/agent-service-control`). The window
  closes after the last of them: it starts the daemon through `make start` and
  verifies, within a bound it owns, that the started daemon answers its health
  read with admission open and reports the checkout's current tip as the commit
  it started from. A start command that finishes with a failure is not
  verified, however healthy the daemon. The restart action succeeds only on
  that verification.

- **Actions after the start.** The registry declares which actions run while
  the daemon serves
  (`local/projects/teleclaude/design/architecture/checkpoint-system`), and the
  platform base declares Blueprint maintenance and publication so, and this
  repository's overlay configuration-schema publication. Such an
  action never runs inside a window and never holds the daemon stopped. When a
  window covers its activation, it runs after that window's start has
  verified, in its precedence waves, while the started daemon serves; when the
  start does not verify, it stays recorded and a later drain performs it while
  no window is open. Its failure is reported like any other action's and
  leaves the daemon serving.

- **Window extent.** A drain that opened a window keeps the daemon stopped
  while any recorded action that runs inside a window remains actionable,
  activations recorded while the window is open included. It starts the daemon
  only on the checkout's tip, once no such action remains actionable and that
  tip's own advancement is registered — its owed set resolved by the commit
  boundary, empty or not.
  Registration waits from that final check until the window has closed, so an
  advancement registered before the close runs inside the window and the daemon
  starts once, after its actions; one registered after the close runs in a
  window of its own. When the tip's advancement is not yet registered at the
  final check, the window registers it itself through the commit boundary's
  recording, over the range from the checkout's previous position to the tip —
  the range that advancement's own hook resolves — and a later recording of the
  same advancement is a repeated recording. A registration the window cannot
  complete leaves the daemon stopped: each restart action the window covered
  ends failed with that refusal's reason, the reason and its time are recorded
  where `make status` reports them, and replaying a restart action once the
  cause is resolved reopens the window on the stopped daemon. When the
  checkout's tip moved after the final check, the window registers that
  advancement in the same way; if it owes the restart action, the start it
  overtook is stopped again within the same window, which runs that
  advancement's actions and starts the daemon from it after them, so the daemon
  is never left serving an advancement whose owed actions that run inside a
  window have not run. An
  advancement that owes no restart runs after the close while the daemon
  serves, as any such activation does. An activation that
  owed the restart action keeps that obligation while any of its records for an
  action that runs inside a window remains, so replaying one of those failed
  actions runs inside a window of its own; replaying a failed action that runs
  while the daemon serves leaves the daemon serving.

- **Window failure.** The window opens only on the outcome `make stop` records
  as stopped — the daemon exited and its relaunch suppressed — including a stop
  that also reports a managed-unit cleanup failure, which is reported with the
  opening (`local/projects/teleclaude/policy/daemon-availability`). Any other
  outcome than stopped or incomplete preparation leaves the window unopened:
  nothing starts, stops or replaces the daemon further, the activation's
  actions stay recorded and unperformed, the refusal is reported at error level
  with its reason, and the reason and its time are recorded where `make status`
  reports them. A failed action inside an open window is reported and the
  window still closes. A start that does not verify
  is the restart action's terminal failure, carrying the start's reason; the
  reason and its time are also recorded where `make status` reports them until
  a later window verifies a start.

<!-- change:commit-maintenance-sheds-platform-work -->

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

<!-- planned-change:commit-maintenance-sheds-platform-work -->

- **Observation.** Every attempt and terminal outcome retains the immutable
  activation and action identity in structured records. The commit boundary
  records a checkout-scoped integrator judgment for every qualifying code
  activation after its owed action records are durable, including a direct main
  commit with no todo candidate. The judgment retains the activation time and
  becomes eligible only after all owed actions succeed, the restart action
  succeeding only on its window's verified start; whether the runtime then
  behaves correctly belongs to the integrator's log judgment, not to the
  action. The drain records the latest maintenance-ready time
  on that marker; if interrupted before recording readiness, the judgment stays
  outstanding for integrator recovery even when action files are absent. A log
  read can discharge it only after that ready time
  with a window covering the activation through completed maintenance. Operational
  anomaly detection observes failed or stale actions. A regular committer has no
  post-commit maintenance log judgment. The standing integrator is woken by the
  activation's settlement announcement, judges the relevant runtime evidence
  after owed actions complete, and owns bounded recovery. The log bug hunter remains a later anomaly backstop. Maintenance
  completion sends no notification to the committer.

<!-- change:commit-maintenance-sheds-platform-work -->

- **Observation.** Every attempt and terminal outcome retains the immutable
  activation and action identity in structured records. The commit boundary
  records a checkout-scoped integrator judgment for every qualifying code
  activation after its owed action records are durable, including a direct main
  commit with no todo candidate. A runtime that an install activates records no
  judgment at its project's commit: the installation inspector judges each
  install (`local/projects/teleclaude/design/architecture/installation`). The
  judgment retains the activation time and becomes eligible only after all owed
  actions succeed; whether the runtime then behaves correctly belongs to the
  integrator's log judgment, not to the action. The drain records the latest
  maintenance-ready time on that marker; if interrupted before recording
  readiness, the judgment stays outstanding for integrator recovery even when
  action files are absent. A log read can discharge it only after that ready
  time with a window covering the activation through completed maintenance.
  Operational anomaly detection observes failed or stale actions. A regular
  committer has no post-commit maintenance log judgment. The standing
  integrator is woken by the activation's settlement announcement, judges the
  relevant runtime evidence after owed actions complete, and owns bounded
  recovery. The log bug hunter remains a later anomaly backstop. Maintenance
  completion sends no notification to the committer.

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

### Use cases

#### UC-PCM1: A commit performs the maintenance its changed paths owe

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a commit on the canonical checkout's main branch changing paths that owe deterministic maintenance
When the commit is recorded
Then each owed maintenance action is performed in the registry's precedence order
And an agent reading the structured records observes the commit, the resolved action set, and each action's outcome
```

#### UC-PCM2: A person's own commit receives the same maintenance as a session's

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a person commits the same paths by hand, with no agent session involved
When the commit is recorded
Then the same maintenance actions are performed as when a session commits those paths
And the person is not asked to perform any of them
```

#### UC-PCM3: A commit owing no deterministic maintenance performs none

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a commit changing only paths that owe no deterministic maintenance
When the commit is recorded
Then no maintenance action is performed
And an agent reading the structured records observes that the resolved action set was empty
```

#### UC-PCM4: A failing maintenance action leaves the commit standing

```gherkin
Given a commit that owes more than one deterministic maintenance action
When one of those actions fails
Then the commit remains recorded exactly as it was made
And the remaining owed actions are still performed
And an agent reading the structured records observes which action failed
```

#### UC-PCM5: A commit outside the canonical main checkout performs no main-only maintenance

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a commit recorded in a todo worktree rather than the canonical checkout's main branch
When the commit is recorded
Then no main-only maintenance action is performed
And the documentation and artifact pipeline is not run from that worktree
And an agent reading the structured records observes that maintenance was skipped, and the location that made it ineligible
```

#### UC-PCM6: An integration merge or fast-forward performs maintenance

```gherkin
Given integration advances canonical main by merge or fast-forward
And the advanced committed change owes deterministic maintenance
When the canonical-root advancement completes
Then its maintenance is recorded and starts without an agent instruction
And the Git operation returns before long-running maintenance finishes
And the terminal reports that automatic maintenance has started in the background, may take some time, and needs no manual installation
And each action eventually has a structured terminal outcome
But the integration worktree performs no maintenance action
```

#### UC-PCM7: Publication uses committed state, not working-tree state

```gherkin
Given a canonical-main commit whose changed paths owe publication
And another registered repository carries source that has not run its own publication action
When commit-boundary maintenance performs the publication action for that recorded range
Then the homes that range touched advance to the committed main tip
And every other repository contribution remains at its previously activated revision
And no unactivated source appears in the generation
```

#### UC-PCM8: Recovery replays the failed action and converges to the main tip

```gherkin
Given a recorded commit range whose publication action failed
And later canonical-main commits or working-tree edits exist
When an agent retries that recorded maintenance action
Then the executor publishes the homes that range touched at the committed main tip
And its structured records identify the replayed range and terminal outcome
And no working-tree state reaches the deployed output
```

#### UC-PCM9: A root commit has an immutable activation range

```gherkin
Given a repository whose canonical main has no parent commit
When its first qualifying commit invokes post-commit maintenance
Then maintenance records an absent before revision and the immutable committed tip
And changed-file resolution includes the complete root-commit tree
And an agent reading the structured records observes that same normalized activation range on every action command and outcome
```

#### UC-PCM10: A tier-documentation commit in the platform home owes publication

```gherkin
Given the platform home carries the installed maintenance hook
And a person or company documentation source inside it participates in the documentation surface
When a commit on the platform home's canonical main records a change to that source
Then committed-state publication is included in the maintenance owed by that activation range
And an agent reading the structured records observes the immutable range and the publication action's terminal outcome
But the same path shape in an ordinary project does not acquire a home-only maintenance binding
```

#### UC-PCM11: A commit returns while maintenance continues

```gherkin
Given a canonical-main commit owes an action that takes longer than the commit itself
When the commit is recorded
Then the Git command returns after handing off the owed action
And the action runs to a separately observable terminal outcome
And the committer receives no maintenance-completion notification
```

#### UC-PCM12: A commit arriving during a drain is not stranded

```gherkin
Given maintenance for one canonical-main advancement is still running
When another advancement records its own owed actions
Then the later actions are processed after the earlier activated state
And neither advancement needs a resident worker or a later commit to trigger processing
```

#### UC-PCM13: An interrupted action is safe to retry

```gherkin
Given one owed action had its effect but was interrupted before success was recorded
And another action for the same activated state already recorded success
When a later maintenance invocation resumes outstanding work
Then the interrupted action converges to its intended state
And the confirmed successful action does not run again
```

#### UC-PCM14: Terminal failure remains visible without a retry loop

```gherkin
Given an owed maintenance action ends in failure
When the drain continues with other owed actions
Then the failed action remains identifiable by its activated state and action identity
And operational anomaly detection can report it
But the drain does not retry that terminal failure indefinitely
```

<!-- planned-change:commit-maintenance-sheds-platform-work -->

#### UC-PCM15: The standing integrator owns maintenance observation

```gherkin
Given a canonical-main change owes daemon restart or publication maintenance
When Git returns before that maintenance finishes
Then the regular committer has no maintenance log-check obligation
And the standing integrator observes the owed action and judges its result after completion
And later anomalies remain discoverable by the log bug hunter
But maintenance completion sends no prompt to the committer
```

<!-- change:commit-maintenance-sheds-platform-work -->

#### UC-PCM15: The standing integrator owns maintenance observation

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

#### UC-PCM16: Direct main commits reach the integrator through their settlement

```gherkin
Given a canonical-main commit was made without a todo candidate
And its changed paths owe maintenance
When its activation settles and the settlement announcement reaches the standing integrator
Then it discovers the retained judgment for that commit even if maintenance has already completed
And judges the changed runtime after the owed actions reach terminal success
But the original committer receives no maintenance log-check obligation
```

#### UC-PCM17: Early or narrow log evidence does not close integrator judgment

```gherkin
Given a canonical-main change still has an owed maintenance action pending
When the standing integrator reads logs before that action succeeds
Then the live-runtime judgment for that change remains outstanding
And after every owed action succeeds, a log read whose window covers the activation and completed maintenance may close it
And a later drain that completes no owed action for that change does not make that read too early
But a read whose window misses that interval does not close it
```

#### UC-PCM18: A master commit in the platform home owes publication

```gherkin
Given the platform home carries the installed maintenance hook
And the home's retained set admits the fixed home master set: the platform home's root AGENTS.master.md, each declared person's and company's root AGENTS.master.md, and each declared company's help-desk/AGENTS.master.md
When a commit on the platform home's canonical main records a change to one of those masters
Then committed-state publication is included in the maintenance owed by that activation range
And an agent reading the structured records observes the immutable range and the publication action's terminal outcome
And no generated AGENTS.md beside those masters enters the commit, because the retained set does not admit it
But the same path shape in an ordinary project does not acquire a home-only maintenance binding
```

<!-- planned-change:commit-maintenance-sheds-platform-work -->

#### UC-PCM19: A restart owed by an integration does not close admission on that integration

```gherkin
Given an integration advances canonical main and its activation owes a daemon restart
And that integration's own accepted work is still running in the daemon
When the stopped-daemon window opens
Then the daemon keeps accepting work while any accepted work is held, up to the window's bound
And preparation begins once the daemon holds no accepted work, or when the bound expires
And the integration completes without having had its own window close admission around it
```

#### UC-PCM20: Steps that change what the daemon runs on run against a stopped daemon

```gherkin
Given a canonical-main advancement owes a daemon restart together with dependency, installation and configuration migration steps
When its maintenance runs
Then the daemon has stopped before the first of those steps begins
And none of those steps begins while a daemon process serves
And the daemon is started after the last of them has a terminal outcome
And an agent reading the structured records observes the window opening, each of those steps' outcomes and the window closing in that order
```

#### UC-PCM21: Unsettled work keeps the window waiting, not the steps running

```gherkin
Given a canonical-main advancement owes a daemon restart
And the daemon holds accepted work that does not settle within its preparation observation window
When the stopped-daemon window opens
Then each expired observation window is reported in the structured records
And no owed step runs while the daemon is draining
And the owed steps that run inside a window run once the daemon has stopped
```

#### UC-PCM22: A failed step still ends with the daemon started and verified

```gherkin
Given a canonical-main advancement owes a daemon restart and another step
When that other step fails inside the stopped-daemon window
Then the remaining owed steps that run inside a window still run
And the daemon is started and verified after the last of them
And the failed step remains recorded as failed with its replay
```

#### UC-PCM23: A start that does not verify leaves its reason where an agent looks first

```gherkin
Given a canonical-main advancement owes a daemon restart
When the daemon started at the window's close does not answer healthy with admission open on the checkout's tip within the window's bound
Then the restart action ends failed with the start's reason
And an agent running make status sees that reason and when it was recorded
```

#### UC-PCM24: A refused stop performs no step

```gherkin
Given a canonical-main advancement owes a daemon restart
When make stop withholds the stop for a reason other than incomplete preparation and the daemon still serves
Then the daemon keeps serving
And none of the activation's owed steps has run
And an agent reading the structured records observes the refusal and its reason
And the activation's owed actions remain recorded for a later drain
```

#### UC-PCM25: Replaying a failed step of a restart-owing activation stops the daemon again

```gherkin
Given an activation that owed a daemon restart recorded one of its steps that run inside a window as failed
When an agent replays that failed step
Then the daemon is stopped before the replayed step runs
And the daemon is started and verified after it
```

#### UC-PCM26: A documentation-only advancement leaves the daemon serving

```gherkin
Given a canonical-main commit in the platform's checkout changing only documentation
When its maintenance runs
Then the daemon keeps serving throughout
And the publication step runs
```

#### UC-PCM27: Advancements recorded during a window share it

```gherkin
Given a stopped-daemon window is open for one canonical-main advancement
When another advancement records its own owed actions before the window closes
Then the later advancement's actions that run inside a window run inside the same window
And the daemon is started once, after those actions of both advancements have terminal outcomes
```

#### UC-PCM28: A stop that does not establish a stopped daemon leaves it untouched with its reason

```gherkin
Given a canonical-main advancement owes a daemon restart
When make stop records an outcome other than stopped or incomplete preparation
Then none of the activation's owed steps has run
And the window neither starts nor replaces the daemon
And an agent running make status sees the stop's reason and when it was recorded
```

#### UC-PCM29: An installation-only advancement stops the daemon

#### UC-PCM30: Installation inside a window leaves sessions running

```gherkin
Given agent sessions run in the tmux server
And a canonical-main advancement owes installation while the tmux server's rendered definition differs from the deployed one
When its maintenance runs inside the stopped-daemon window
Then the sessions are still running after the window closes
And an agent reading the structured records observes that the tmux server definition change was deferred
```

#### UC-PCM31: A stop that stopped the daemon but failed a unit cleanup still opens the window

```gherkin
Given a canonical-main advancement owes a daemon restart
When make stop records that the daemon stopped with its relaunch suppressed and a managed-unit cleanup failed
Then the window opens and the owed steps run
And an agent reading the structured records observes the cleanup failure
```

#### UC-PCM32: An advancement still registering when the window's last step ends shares the window

```gherkin
Given a stopped-daemon window is open for one canonical-main advancement
And another canonical-main commit has advanced the checkout but its owed actions are not yet recorded when the window's last owed step ends
When the window reaches its final check
Then that commit's owed actions are recorded once, and those that run inside a window run inside the same window
And the daemon is started once, from that commit, after they have terminal outcomes
```

#### UC-PCM33: A start overtaken by a further advancement is stopped again before that advancement runs

```gherkin
Given a stopped-daemon window has started the daemon after its last owed step
And another canonical-main commit that owes a daemon restart advanced the checkout while that start was in progress
When the window checks the start it made
Then the daemon is stopped again before any of that commit's owed actions runs
And its actions that run inside a window run inside the same window
And the daemon is started and verified from that commit after they have terminal outcomes
```

#### UC-PCM34: A tip whose owed actions cannot be recorded leaves the daemon stopped with its reason

```gherkin
Given a stopped-daemon window has run its last owed step
And the checkout's tip is a commit whose owed actions cannot be recorded
When the window tries to record them
Then the daemon stays stopped
And each restart action the window covered ends failed with the refusal's reason
And an agent running make status sees that reason and when it was recorded
And replaying a restart action after the cause is resolved records the tip's owed actions, runs those that run inside a window and starts the daemon from the tip
```

#### UC-PCM35: A code commit keeps the daemon down only for the steps that need it stopped

```gherkin
Given a canonical-main commit changing daemon source owes a daemon restart, Blueprint maintenance and publication
When its maintenance runs
Then the daemon is started and verified before Blueprint maintenance and publication begin
And Blueprint maintenance and publication run while the started daemon serves
And an agent reading the structured records observes the window closing before either of them starts
And replaying either of them after a failure leaves the daemon serving
```

<!-- change:commit-maintenance-sheds-platform-work -->

#### UC-PCM19: A restart owed by an integration does not close admission on that integration

#### UC-PCM20: Steps that change what the daemon runs on run against a stopped daemon

#### UC-PCM21: Unsettled work keeps the window waiting, not the steps running

#### UC-PCM22: A failed step still ends with the daemon started and verified

#### UC-PCM23: A start that does not verify leaves its reason where an agent looks first

#### UC-PCM24: A refused stop performs no step

#### UC-PCM25: Replaying a failed step of a restart-owing activation stops the daemon again

#### UC-PCM26: A documentation-only advancement leaves the daemon serving

#### UC-PCM27: Advancements recorded during a window share it

#### UC-PCM28: A stop that does not establish a stopped daemon leaves it untouched with its reason

#### UC-PCM29: An installation-only advancement stops the daemon

#### UC-PCM30: Installation inside a window leaves sessions running

#### UC-PCM31: A stop that stopped the daemon but failed a unit cleanup still opens the window

#### UC-PCM32: An advancement still registering when the window's last step ends shares the window

#### UC-PCM33: A start overtaken by a further advancement is stopped again before that advancement runs

#### UC-PCM34: A tip whose owed actions cannot be recorded leaves the daemon stopped with its reason

#### UC-PCM35: A code commit keeps the daemon down only for the steps that need it stopped

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

<!-- planned-change:commit-maintenance-sheds-platform-work -->

## Known caveats

- Nothing gates an advancement of the canonical checkout while the window
  starts the daemon: a commit or fast-forward that lands during the start
  changes the files the starting daemon loads. Such a daemon can begin serving
  that advancement's code for the moments between its start and the window's
  check after it, which stops it again before the advancement's owed actions
  run.
- A commit-boundary registration that arrives while a window is closing waits
  for that close, so the commit or merge whose hook records it returns only
  after the window's start has been verified or has failed.

<!-- change:commit-maintenance-sheds-platform-work -->

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

## See Also

- docs/local/adr/0087-mechanical-maintenance-executes-in-a-hook.md — the decision this contract realizes.
- docs/local/adr/0100-commit-maintenance-drains-after-hook-return.md — why maintenance execution no longer holds Git open.

<!-- planned-change:commit-maintenance-sheds-platform-work -->

- docs/local/adr/0124-maintenance-replaces-the-daemon-inside-a-stopped-window.md — why an activation owing a restart runs its steps against a stopped daemon.

- docs/local/adr/0127-maintenance-runs-serving-tolerant-steps-after-the-verified-start.md — why the steps that replace nothing the daemon runs on run after the window's verified start.

<!-- change:commit-maintenance-sheds-platform-work -->

<!-- /planned-change:commit-maintenance-sheds-platform-work -->

- docs/local/design/architecture/checkpoint-system.md — the matcher and registry this surface consumes.
- docs/local/spec/feature/reconciliation/project-plumbing-convergence.md — which hooks a project has installed, and when.
