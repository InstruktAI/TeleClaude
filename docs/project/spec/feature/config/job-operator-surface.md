---
description: Operator/agent front door to the declarative job model — `telec jobs` lists every job a project can see, distinguishing local, subscribed, and available-but-unsubscribed published jobs; shows each job's runtime status (last run, last outcome, next due); subscribes to or unsubscribes from a published job; and runs a job on demand. The surface is a read/control layer over the existing jobs HTTP API, runner run-state, and project config, never a parallel store.
delivered_by:
  - generic-job-operator-surface
---

# Job Operator Surface — Spec

## What it is

The `telec jobs` command group is the operator- and agent-facing front door to the
declarative job model (`project/spec/feature/config/job-declaration-model`) and the
runner's closed-loop run state (`project/design/architecture/jobs-runner`). It
answers, from the CLI, the three questions that job handling otherwise left
unanswerable without reading config files and state JSON by hand: what is
configured and available, how is each job doing at runtime, and let me turn one on
or off or run it now.

A job's identity is its execution pointer, as the declaration model defines it —
the procedure snippet ID of an agent job, the module stem of a script job. The
surface names jobs by that identity everywhere, and never by a separate name.

The surface resolves the invoking project and reports against that project's
effective and available job set:

- **list** shows every job the project can see, each tagged with its relationship
  to the project: a **local** job (declared in the project's own jobs, with no
  published counterpart), a **subscribed** job (a published job the project's
  jobs carry an active entry for), or an **available** job (a published job the
  project does not currently subscribe to). The available jobs are what makes a
  published job discoverable before a project opts in.
- **status** shows each job's runtime status read from the runner's run state — the
  last run time, the last run's outcome, and the next due time derived from the
  job's `when` schedule. A job that has never run shows no last run and no last
  outcome, but still shows a next due derived from its schedule.
- **enable** / **disable** turn the project's subscription to a published job on
  and off. Enabling adds or activates the project's subscribing entry for that
  job's pointer; disabling deactivates the entry it finds. Because a subscription
  exists only against a published job, naming a job that is not published — a
  local job or an unknown pointer — fails without writing anything, and so does
  disabling a job the project does not subscribe to. The change is observable on
  the next list.
- **run** dispatches a job on demand through the existing run path.

Runtime status the surface displays is read from the runner's run state through the
jobs HTTP API; subscription is a config write to the project's own jobs. The surface
owns no job state of its own — it is a read/control surface over the existing API,
runner run-state, and project config.

## Canonical fields

### Use cases

#### UC-JOS-1: List distinguishes local, subscribed, and available jobs

```
Given a project with a local job, a published job it subscribes to, and a published job it does not subscribe to
When an operator or agent lists jobs at the CLI
Then all three jobs appear, each named by its execution pointer
And each is marked with its relationship to the project — local, subscribed, or available
```

#### UC-JOS-2: Status shows last run, last outcome, and next due

```
Given a job that has run before and carries a schedule
When an operator or agent requests job status at the CLI
Then the job shows the last run time and the last run's outcome read from the runner's run state
And it shows the next due time derived from the job's schedule
```

#### UC-JOS-3: Status of a never-run job shows next due without last run

```
Given a configured job that has never run
When an operator or agent requests job status at the CLI
Then the job shows no last run and no last outcome
And it still shows a next due time anchored on when the runner first saw the job
```

#### UC-JOS-4: Enabling a published job subscribes the project to it

```
Given a published job the project does not subscribe to
When an operator or agent enables the job at the CLI
Then the project's own jobs carry an active subscribing entry for that job's pointer
And the job appears as subscribed on the next list
```

#### UC-JOS-5: Disabling a published job unsubscribes the project from it

```
Given a published job the project subscribes to
When an operator or agent disables the job at the CLI
Then the project's subscribing entry for that job's pointer is deactivated
And the job appears as available rather than subscribed on the next list
```

#### UC-JOS-6: Subscribing to a job that is not published is rejected without a write

```
Given a job that is not published — a local job or an unknown pointer
When an operator or agent tries to enable or disable it at the CLI
Then the command fails naming the job
And the project's configuration is left unchanged
```

#### UC-JOS-7: Run a job on demand

```
Given a configured job
When an operator or agent runs the job on demand at the CLI
Then the job is dispatched through the existing run path for the invoking project
And the operator is told the run was accepted
```

#### UC-JOS-8: Disabling a job the project never subscribed to writes nothing

```
Given a published job the project has no subscribing entry for
When an operator or agent disables the job at the CLI
Then the command reports that the project does not subscribe to it
And the project's configuration is left unchanged
```

## Known caveats

- The runtime status the surface shows is always the runner's recorded run state,
  read through the jobs HTTP API; the surface never recomputes or stores outcome,
  so its values track the runner exactly and add no second source of truth.
- The surface is scoped to the invoking project: list and status reflect that
  project's effective and available set, and enable/disable write that project's
  own jobs. Cross-project operation is out of scope.
- The next-due time is a projection from the `when` schedule and the run state; it is
  advisory, not a guarantee — the host trigger fires on its own cadence and a job
  with an open run is not re-dispatched until its run closes.
- A subscribing entry carries the project's own overrides for the published
  declaration. Enable and disable turn that entry on and off; they never author or
  remove the overrides an operator has set on it.
