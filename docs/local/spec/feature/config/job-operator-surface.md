---
description: Operator/agent front door to the declarative job model — `telec jobs`
  lists every job a project can see, distinguishing local, subscribed, and available-but-unsubscribed
  published jobs; shows each job's runtime status (last run, last outcome, next due);
  subscribes to or unsubscribes from a published job; and runs a job on demand. The
  surface is a read/control layer over the existing jobs HTTP API, runner run-state,
  and project config, never a parallel store.
---

# Job Operator Surface — Spec

## What it is

The `telec jobs` command group is the operator- and agent-facing front door to the
declarative job model (`local/projects/teleclaude/spec/feature/config/job-declaration-model`) and the
runner's closed-loop run state (`local/projects/teleclaude/design/architecture/jobs-runner`). It
answers, from the CLI, the three questions that job handling otherwise left
unanswerable without reading config files and state JSON by hand: what is
configured and available, how is each job doing at runtime, and let me turn one on
or off or run it now.

A job's identity is its declared name, as the declaration model defines it. The
surface names jobs by that name everywhere — in its output and in the argument
every job-targeting subcommand takes — and never by the execution pointer.

The surface resolves the invoking project and reports against that project's
effective and available job set:

- **list** shows every job the project can see, each tagged with its relationship
  to the project: a **local** job (declared in the project's own jobs, with no
  published counterpart), a **subscribed** job (a published job the project's
  jobs carry an active entry for), or an **available** job (a published job the
  project does not currently subscribe to). The available jobs are what makes a
  published job discoverable before a project opts in.
- **status** shows each job's runtime status read from the runner's run state — the
  last run time, the last run's outcome, and the next due time projected from the
  job's `when` schedule against that run state. A job that has never run shows no
  last run and no last outcome, but still shows a next due, projected from when the
  runner first saw the job — the same instant the runner itself anchors a first run on.
  A job the runner runs on its subscribers' schedules rather than its own shows the
  earliest next due across its enabled subscribers' schedules, and no next due when it
  has no enabled subscriber. An available job has no run state and shows none.
- **enable** / **disable** turn the project's subscription to a published job on
  and off. Enabling adds a subscribing entry carrying the job's name, or activates
  the one the project already has; disabling deactivates the entry it finds. Because
  a subscription exists only against a published job, naming a job that is not
  published — a local job or an unknown name — fails without writing anything, and
  disabling a job the project does not subscribe to reports that and writes nothing.
  The change is observable on the next list.
- **run** dispatches one of the project's effective jobs on demand through the
  existing run path, in the invoking project only.

Runtime status the surface displays is read from the runner's run state through the
jobs HTTP API; subscription is a config write to the project's own jobs. The surface
owns no job state of its own — it is a read/control surface over the existing API,
runner run-state, and project config.

## Canonical fields

### Use cases

#### UC-JOS-1: An operator finds the jobs a project can use

```gherkin
Given the project has a local job, a published job it subscribes to, and a published job it does not subscribe to
When the operator asks their agent to list the project's jobs
Then all three jobs appear under their declared names
And each is identified as local, subscribed, or available
```

#### UC-JOS-2: An operator checks how a job is doing

```gherkin
Scenario: A job that has run shows its recent outcome and next expected run
  Given a job has run before and has a schedule
  When the operator asks their agent for that job's status
  Then the operator sees its last run, its outcome, and when it is next expected

Scenario: A job that has never run still shows when it is next expected
  Given a scheduled job has never run
  When the operator asks their agent for that job's status
  Then the operator sees no last run or outcome
  And still sees when the first run is expected

Scenario: A job run on subscriber schedules shows the earliest next run
  Given two enabled subscriber schedules produce different next-run times
  When the operator asks their agent for the published job's status
  Then the earlier subscriber time is shown
  And no next run is shown when there are no enabled subscribers
```

#### UC-JOS-3: Status of a never-run job shows next due without last run

#### UC-JOS-4: An operator subscribes the project to a published job

```gherkin
Scenario: Subscribe to a published job
  Given a published job the project does not subscribe to
  When the operator asks their agent to subscribe the project to it
  Then the job appears as subscribed on the next list

Scenario: A local or unknown job cannot be subscribed
  Given a local job or an unknown job name
  When the operator asks their agent to subscribe the project to it
  Then the request is refused naming the job
  And no subscription is created
```

#### UC-JOS-5: An operator unsubscribes the project from a published job

```gherkin
Scenario: Unsubscribe from a published job
  Given a published job the project subscribes to
  When the operator asks their agent to unsubscribe the project from it
  Then the job appears as available rather than subscribed on the next list

Scenario: A job the project does not subscribe to cannot be unsubscribed
  Given a local or unknown job, or a published job with no project subscription
  When the operator asks their agent to unsubscribe the project from it
  Then the request is refused naming the condition
  And no subscription is removed
```

#### UC-JOS-6: Subscribing to a job that is not published is rejected without a write

#### UC-JOS-7: An operator runs a job on demand

```gherkin
Given a job in the invoking project's effective job set
When the operator asks their agent to run it on demand
Then the job is accepted for that project only
And the operator is told the run was accepted
```

#### UC-JOS-8: Disabling a job the project never subscribed to writes nothing

#### UC-JOS-9: Status of a subscriber-scheduled job shows its earliest subscriber due

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
  remove the overrides an operator has set on it, and leave every other job entry,
  every other key of the project's configuration, and its `${VAR}` references as they were.
