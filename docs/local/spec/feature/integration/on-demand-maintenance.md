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
  canonical main. From any other checkout, the platform's installation or a
  directory holding no `teleclaude.yml`, it refuses before any step runs and
  names the eligible location.

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

- **Other disruptive steps.** Nothing a run performs stops, restarts or
  reloads a running service. Reloading the
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

- **Report order.** Uncommitted edits come first, then the step outcomes in
  declared order, then earlier failures, and owed disruptive steps last.

- **Listing.** `telec sync --list` prints, in order, every step the root's
  registry declares with what a run would do with it — perform it, or only
  report whether it is owed — and changes nothing.

- **Concurrency.** A run started while commit-boundary maintenance is still
  running never performs a step at the same time as that run, and leaves both
  runs' records accurate.
- **Repetition.** A run repeated with nothing changed leaves deployed output and
  machine state as the previous run left them.

### Use cases

#### UC-ODM1: An operator runs the root’s maintenance on demand

```gherkin
Scenario: Apply the root's declared maintenance
  Given an operator wants to run maintenance from an eligible canonical checkout
  When their agent runs `telec sync`
  Then every maintenance step declared by that root is attempted in order
  And the operator sees each step's result as it completes

Scenario: Continue maintenance after a step fails
  Given the root's maintenance has later steps still owed
  When one step fails during the run
  Then every later step is still attempted
  And the run reports the failure and exits unsuccessfully

Scenario: See uncommitted changes before the steps run
  Given the root's working tree has uncommitted edits
  When an operator runs `telec sync`
  Then the changed paths and known holders are reported before the first step

Scenario: Leave other running services alone
  Given installation would deploy a changed definition for another running service
  When an operator runs `telec sync`
  Then the service remains running and its changed definition is reported as owed
  And the report names the command that deploys it

Scenario: See the recovery route for an earlier failure
  Given an earlier commit-boundary maintenance run recorded a step as failed
  When an operator runs `telec sync` in that root
  Then the report names the failed step and its replay command
  And the failed record remains and its owning integrator is named

Scenario: Refuse a run from an ineligible checkout
  Given an operator runs `telec sync` outside canonical main
  When the command begins
  Then it refuses before any step runs
  And names an eligible maintenance checkout
```

#### UC-ODM2: A failed step does not stop the rest

#### UC-ODM3: A downstream project converges its own plumbing

#### UC-ODM4: A run in the platform's checkout replaces the daemon

#### UC-ODM5: Nothing owed adds nothing

#### UC-ODM7: An earlier recorded failure is named with its replay

#### UC-ODM8: An operator previews the root’s maintenance steps

```gherkin
Given an operator wants to inspect the maintenance plan before running it
When their agent runs `telec sync --list`
Then the operator sees the root's declared steps in order
And no step runs and no maintenance record is written
```

#### UC-ODM9: A run outside an eligible maintenance checkout refuses

#### UC-ODM10: Uncommitted edits are named, and never published

#### UC-ODM11: A run during automatic maintenance does not collide with it

#### UC-ODM12: A repeated run changes nothing

#### UC-ODM13: Help presents the fallback

#### UC-ODM14: A step with nothing to act on completes without failing

#### UC-ODM15: Installation leaves running services alone

## See Also

- docs/local/spec/feature/context/sync-pipeline-orchestration.md — publication, one of the steps.
- docs/local/adr/0094-publication-activates-from-recorded-commits.md — committed-state activation and replay-based recovery.
