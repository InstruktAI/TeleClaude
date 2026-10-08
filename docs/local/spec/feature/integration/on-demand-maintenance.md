---
description: telec sync performs a root's commit-boundary maintenance on demand, step
  by step through the same executor, leaves disruptive steps undone, and ends by naming
  what is still owed and how to do it.
visibility: internal
---

# On-Demand Maintenance — Spec

## Required reads

@docs/local/spec/feature/integration/post-commit-maintenance.md

## What it is

Commit-boundary maintenance performs the steps a canonical-main advancement
owes (`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`).
On-demand maintenance is the manual fallback for that automation: `telec sync`,
run in a root, performs that root's maintenance steps now. It serves the case
where the automation did not run, or ran and left something wrong, and lets the
caller see at which step a failure happens.

The steps are every maintenance action the root's registry declares — the
platform base merged with the root's own overlay, the same merged model the
commit boundary reads. `telec sync` keeps no list of its own, so the fallback
cannot drift from the automation. A manual run has no commit range, so changed
paths narrow nothing: every declared step is owed, including converging the
root's own plumbing. A step with nothing to act on in a root completes and says
so; installation in a root that declares nothing to install reports exactly
that, and does not fail.

Publication is one of those steps and keeps its own contract
(`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`).

## Canonical fields

<!-- planned-change:help-desks-as-deployment-output -->

- **Location.** A run acts only from the canonical checkout on its main branch.
  From a worktree, from a canonical checkout on another branch, or from a
  directory holding no `teleclaude.yml`, it refuses before any step runs and
  names where to run it instead.
- **Steps.** The owed steps run in the registry's declared order through the
  commit-boundary executor, with the same structured attempt and outcome
  records, marked as an on-demand run. Each step's outcome is reported as it
  completes. A failed step never stops a later one. A run in which any step
  failed exits non-zero. The run leaves no queued obligation behind: its caller
  holds the outcome, and running it again is its recovery.
- **Uncommitted edits.** The step set is resolved from the root's committed
  declaration. Publication reads committed state alone, under its own contract.
  Every other step reads the canonical checkout as it stands, exactly as it does
  at the commit boundary, so an uncommitted edit there can reach its output.
  When the root's repository holds uncommitted changes, the run says so before
  its first step, naming the uncommitted paths and, where known, the sessions
  holding them, and then performs every step. Uncommitted edits never make a run
  refuse or skip a step.
- **Plumbing.** Every project's steps include converging that project's own
  plumbing, whatever else its declaration carries.
- **Disruptive steps.** Nothing a run performs stops, restarts or reloads a
  running service. Restarting the daemon and reloading the terminal interface
  are never performed by a run. During a run, installation deploys none of the
  service definitions TeleClaude's installation renders, and stops, restarts or
  reloads no running service. It may still start a service that is not running,
  and a component it sets up may still rewrite its own scheduler configuration
  where that reloads nothing. After its steps, the run
  reports each such change that is owed, with the command that performs it. A
  restart or reload is owed when a process it refreshes started from an earlier
  commit than the one the run converged, and the changes between the two owe that
  step under the root's own bindings. Deploying service definitions is owed when
  a deployed definition differs from what installation would deploy, or a
  service is due for withdrawal. A run that establishes nothing is owed adds
  nothing. A run that cannot establish whether a change is owed, such as which
  commit a running process started from, says so.
- **Earlier failures.** A step that an earlier commit-boundary run recorded as
  failed is named after the run's own steps, with the replay that recovers it.
  That replay re-runs the recorded action for its original range. The run never
  replaces or clears that record. The report names the standing integrator as
  the owner of that replay.
- **Report order.** Uncommitted edits come first, then step outcomes, then
  earlier failures, and owed disruptive steps last.
- **Listing.** `telec sync --list` prints, in order, every step the root's
  registry declares with what a run would do with it — perform it or only
  report whether it is owed — and changes nothing.
- **Concurrency.** A run started while commit-boundary maintenance is still
  running never performs a step at the same time as that run, and leaves both
  runs' records accurate.
- **Repetition.** A run repeated with nothing changed leaves deployed output and
  machine state as the previous run left them.

<!-- change:help-desks-as-deployment-output -->

- **Location.** A run acts only from the canonical checkout on its main branch.
  From a worktree, from a canonical checkout on another branch, or from a
  directory holding no `teleclaude.yml`, it refuses before any step runs and
  names where to run it instead.
- **Steps.** The owed steps run in the registry's declared order through the
  commit-boundary executor, with the same structured attempt and outcome
  records, marked as an on-demand run. Each step's outcome is reported as it
  completes. A failed step never stops a later one. A run in which any step
  failed exits non-zero. The run leaves no queued obligation behind: its caller
  holds the outcome, and running it again is its recovery.
- **Uncommitted edits.** The step set is resolved from the root's committed
  declaration. Publication reads committed state, and the masters a repository
  ignores from disk, under its own contract.
  Every other step reads the canonical checkout as it stands, exactly as it does
  at the commit boundary, so an uncommitted edit there can reach its output.
  When the root's repository holds uncommitted changes, the run says so before
  its first step, naming the uncommitted paths and, where known, the sessions
  holding them, and then performs every step. Uncommitted edits never make a run
  refuse or skip a step.
- **Plumbing.** Every project's steps include converging that project's own
  plumbing, whatever else its declaration carries.
- **Disruptive steps.** Nothing a run performs stops, restarts or reloads a
  running service. Restarting the daemon and reloading the terminal interface
  are never performed by a run. During a run, installation deploys none of the
  service definitions TeleClaude's installation renders, and stops, restarts or
  reloads no running service. It may still start a service that is not running,
  and a component it sets up may still rewrite its own scheduler configuration
  where that reloads nothing. After its steps, the run
  reports each such change that is owed, with the command that performs it. A
  restart or reload is owed when a process it refreshes started from an earlier
  commit than the one the run converged, and the changes between the two owe that
  step under the root's own bindings. Deploying service definitions is owed when
  a deployed definition differs from what installation would deploy, or a
  service is due for withdrawal. A run that establishes nothing is owed adds
  nothing. A run that cannot establish whether a change is owed, such as which
  commit a running process started from, says so.
- **Earlier failures.** A step that an earlier commit-boundary run recorded as
  failed is named after the run's own steps, with the replay that recovers it.
  That replay re-runs the recorded action for its original range. The run never
  replaces or clears that record. The report names the standing integrator as
  the owner of that replay.
- **Report order.** Uncommitted edits come first, then step outcomes, then
  earlier failures, and owed disruptive steps last.
- **Listing.** `telec sync --list` prints, in order, every step the root's
  registry declares with what a run would do with it — perform it or only
  report whether it is owed — and changes nothing.
- **Concurrency.** A run started while commit-boundary maintenance is still
  running never performs a step at the same time as that run, and leaves both
  runs' records accurate.
- **Repetition.** A run repeated with nothing changed leaves deployed output and
  machine state as the previous run left them.

<!-- /planned-change:help-desks-as-deployment-output -->

### Use cases

#### UC-ODM1: A run performs the root's maintenance step by step

```gherkin
Given an agent in the canonical checkout of a project on its main branch
When the agent runs telec sync
Then every maintenance step the project's registry declares runs in declared order
And the agent sees each step's outcome as that step completes
And the structured records hold the same per-step outcomes commit-boundary maintenance records
```

#### UC-ODM2: A failed step does not stop the rest

```gherkin
Given a root whose maintenance includes more than one step
When one step fails during telec sync
Then every later step still runs
And the agent sees which step failed and its outcome
And telec sync exits non-zero
```

#### UC-ODM3: A downstream project converges its own plumbing

```gherkin
Given a downstream project whose installed plumbing lags its declaration
When an agent runs telec sync in that project's canonical checkout on main
Then the project's plumbing is converged
And the project's capability-gated publication runs
And no step carried only by another project's declaration runs
```

#### UC-ODM4: A run never restarts, and names an owed restart

```gherkin
Given the running daemon started from code older than the code telec sync just converged
When telec sync finishes its steps
Then the daemon has not been restarted
And the agent's last output from the run states that a restart is owed and names the command that performs it
```

#### UC-ODM5: Nothing owed adds nothing

```gherkin
Given the running daemon and terminal interface run the code telec sync just converged
When telec sync finishes its steps
Then the run reports no owed restart or reload
```

#### UC-ODM6: An undeterminable owed restart is stated, not hidden

```gherkin
Given telec sync cannot establish which code the running daemon started from
When telec sync finishes its steps
Then the agent sees that whether a restart is owed could not be established
```

#### UC-ODM7: An earlier recorded failure is named with its replay

```gherkin
Given an earlier commit-boundary maintenance run recorded a step as failed
When an agent runs telec sync in that root
Then the run names that failed step and the command that replays it for its original range
And the failed record remains for that replay
And the agent is told that the standing integrator owns that replay
```

#### UC-ODM8: Listing changes nothing

```gherkin
Given an agent in a root's canonical checkout on main
When the agent runs telec sync --list
Then the agent sees the steps a run would perform there, in order
And no step runs and no record is written
```

#### UC-ODM9: A run outside canonical main refuses

```gherkin
Given an agent in a todo worktree, or in a canonical checkout on a branch other than main
When the agent runs telec sync
Then telec sync refuses before any step runs
And the agent is told to run it from the canonical checkout on main
```

#### UC-ODM10: Uncommitted edits are named, and never published

```gherkin
Given a root whose working tree holds uncommitted edits
When an agent runs telec sync there
Then before the first step the agent sees those uncommitted paths and, where known, the sessions holding them
And every step runs
And publication publishes the committed main tip
And no uncommitted edit appears in the published output
```

#### UC-ODM11: A run during automatic maintenance does not collide with it

```gherkin
Given commit-boundary maintenance for a recent advancement is still running
When an agent runs telec sync in the same root
Then no step runs at the same time in both
And both runs' outcome records remain accurate
```

#### UC-ODM12: A repeated run changes nothing

```gherkin
Given telec sync has just completed in a root with every step succeeding
And nothing has changed since
When an agent runs telec sync again
Then deployed output and machine state remain as the first run left them
```

#### UC-ODM13: Help presents the fallback

```gherkin
Given an agent unsure how to recover a root after maintenance did not run
When the agent reads telec sync's help
Then the help describes it as the manual fallback for commit-boundary maintenance
And states that it performs the root's maintenance steps, leaves restarts and reloads undone, and names what is owed
```

#### UC-ODM14: A step with nothing to act on completes without failing

```gherkin
Given a root that declares nothing to install and does not subscribe code
When an agent runs telec sync in that root's canonical checkout on main
Then the installation step runs and reports that there is nothing to install
And it completes successfully
And it does not make telec sync exit non-zero
```

#### UC-ODM15: Installation leaves running services alone

```gherkin
Given a service whose definition TeleClaude's installation renders differs from the deployed one
When an agent runs telec sync in that root's canonical checkout on main
Then installation runs without deploying that definition or restarting any service
And the run ends by stating that deploying the changed service definitions is owed and names the command that performs it
```

## See Also

- docs/local/spec/feature/context/sync-pipeline-orchestration.md — publication, one of the steps.
- docs/local/adr/0094-publication-activates-from-recorded-commits.md — committed-state activation and replay-based recovery.
