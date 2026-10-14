---
description: telec sync performs a root's commit-boundary maintenance on demand, step
  by step through the same executor, and ends by naming what is still owed and how to
  do it.
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

- **Location.** A run acts from an eligible maintenance checkout under
  `local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`:
  canonical main or the identified installed release checkout. From any other
  checkout or a directory holding no `teleclaude.yml`, it refuses before any
  step runs and names the eligible location.

- **Steps.** The owed steps run in the registry's declared order through the
  commit-boundary executor, with the same structured attempt and outcome
  records, marked as an on-demand run. Each step's outcome is reported as it
  completes. A failed step never stops a later one. A run in which any step
  failed exits non-zero. The run leaves no queued obligation behind: its caller
  holds the outcome, and running it again is its recovery.

- **Event-only actions.** An action that only event bindings name is not a
  step: a run neither performs nor lists it, because only an event supplies what
  it acts on (`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`).

- **Uncommitted edits.** The step set is resolved from the root's committed
  declaration. Publication and Blueprint extraction read committed snapshots
  under their owning contracts. Other steps read the canonical checkout as it
  stands. A dirty checkout is reported before the first step, including paths
  and known holders, and every step still runs.
- **Blueprint recovery.** A code-enabled project's declared steps include
  Blueprint maintenance. The run converges its shared cache to committed
  canonical main under `sdlc/spec/codebase-blueprint`. An already current cache
  completes without extraction; failure is a failed step. Existing recorded
  activation failures retain the earlier-failure reporting contract below.

- **Plumbing.** Every project's steps include converging that project's own
  plumbing, whatever else its declaration carries.

- **Daemon replacement.** In a root whose registry declares the restart
  action, every run owes the daemon's replacement and is performed inside the
  stopped-daemon window that commit-boundary maintenance uses
  (`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`).
  The run reports the window's opening, or why it did not open, and the start's
  verification, or why it did not verify; a run whose window did not open or
  whose start did not verify exits non-zero. A commit activation owing the
  restart action that is recorded during the run, or that overtakes its start,
  is not the run's to perform: the run leaves the daemon stopped, reports the
  activation it leaves to the drain, and the drain that performs it starts the
  daemon through that activation's own window. A commit activation that owes no
  restart leaves the run's start unchanged and is drained while the daemon
  serves.
- **Other disruptive steps.** Apart from the daemon's replacement, nothing a
  run performs stops, restarts or reloads a running service. Reloading the
  terminal interface is never performed by a run. During a run, installation
  deploys none of the service definitions TeleClaude's installation renders,
  and stops, restarts or reloads no running service. It may still start a
  service that is not running, other than the daemon, and a component it sets
  up may still rewrite its own scheduler configuration where that reloads
  nothing. After its steps, the run reports each such change that is owed, with
  the command that performs it. A reload is owed when a process it refreshes
  started from an earlier commit than the one the run converged, and the
  changes between the two owe that step under the root's own bindings.
  Deploying service definitions is owed when a deployed definition differs from
  what installation would deploy, or a service is due for withdrawal. A run
  that establishes nothing is owed adds nothing. A run that cannot establish
  whether a change is owed, such as which commit a running process started
  from, says so.

- **Earlier failures.** A step that an earlier commit-boundary run recorded as
  failed is named after the run's own steps, with the replay that recovers it.
  That replay re-runs the recorded action for its original range. The run never
  replaces or clears that record. The report names the standing integrator as
  the owner of that replay.

- **Report order.** Uncommitted edits come first, then the daemon's stop when
  the run replaces it, then step outcomes, then the daemon's start and its
  verification, then earlier failures, and owed disruptive steps last.
- **Listing.** `telec sync --list` prints, in order, every step the root's
  registry declares with what a run would do with it — perform it, replace the
  daemon around the run, or only report whether it is owed — and changes
  nothing.

- **Concurrency.** A run started while commit-boundary maintenance is still
  running never performs a step at the same time as that run, and leaves both
  runs' records accurate.
- **Repetition.** A run repeated with nothing changed leaves deployed output and
  machine state as the previous run left them.

### Installed release source

An on-demand run in an installed release checkout resolves its declaration and
committed-source consumers from the selected installed commit. Publication uses
`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`.
The on-demand run preserves the release checkout's selected source and its
ordinary disruptive-step deferral contract.

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

#### UC-ODM4: A run in the platform's checkout replaces the daemon

```gherkin
Given an agent in the platform's canonical checkout
When the agent runs telec sync
Then the run is performed inside the stopped-daemon window
And the agent sees the window open before the first step and the daemon's verified start after the last
```

#### UC-ODM5: Nothing owed adds nothing

```gherkin
Given the running terminal interface runs the code telec sync just converged
When telec sync finishes its steps
Then the run reports no owed reload
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

#### UC-ODM9: A run outside an eligible maintenance checkout refuses

```gherkin
Given an agent in a todo worktree or another checkout that is neither canonical main nor the installed release checkout
When the agent runs telec sync
Then telec sync refuses before any step runs
And the agent is told to run it from an eligible maintenance checkout
```

#### UC-ODM10: Uncommitted edits are named, and never published

```gherkin
Given a root whose working tree holds uncommitted edits
When an agent runs telec sync there
Then before the first step the agent sees those uncommitted paths and, where known, the sessions holding them
And every step runs
And publication publishes the committed source selected for that checkout
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
And states that it performs the root's maintenance steps, stops the daemon before them and starts it after them in the platform's checkout, leaves reloads undone, and names what is owed
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
- docs/local/adr/0124-maintenance-replaces-the-daemon-inside-a-stopped-window.md — why an owed replacement stops the daemon for the whole run.
