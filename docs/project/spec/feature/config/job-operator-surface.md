---
description: Operator/agent front door to the declarative job model — `telec jobs` lists configured and available jobs distinguishing local, enabled-global, and available-global; shows each job's runtime status (last run, last outcome, next due); toggles a global job's per-project enable overlay; and runs a job on demand. The surface is a read/control layer over the existing jobs HTTP API and runner run-state, never a parallel store.
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

The surface resolves the invoking project and reports against that project's
effective and available job set:

- **list** shows every job the project can see, each tagged with its availability:
  a **local** job (declared in the project overlay, not in the global registry), an
  **enabled** global job (a registry job the project's enable overlay turns on), or
  an **available** global job (a registry job the project has not enabled). The
  available-but-not-enabled jobs are what makes a global job discoverable before a
  project opts in.
- **status** shows each job's runtime status read from the runner's run state — the
  last run time, the last run's outcome, and the next due time derived from the
  job's `when` schedule. A job that has never run shows no last run and no last
  outcome, but still shows a next due derived from its schedule.
- **enable** / **disable** toggle a global job's per-project enable overlay (the
  `enabled` flag under the project's `jobs` mapping, per the declaration model).
  Because the enable overlay only applies to global registry jobs, enabling or
  disabling a name that is not a global job — a local job or an unknown name —
  fails without writing anything. The change is observable on the next list.
- **run** dispatches a job on demand through the existing run path.

Runtime status the surface displays is read from the runner's run state through the
jobs HTTP API; enablement is a config write to the project overlay. The surface
owns no job state of its own — it is a read/control surface over the existing API,
runner run-state, and config overlay.

## Canonical fields

### Use cases

#### UC-JOS-1: List distinguishes local, enabled-global, and available-global jobs

```
Given a project with a local job, a global job it has enabled through the overlay, and a global job available but not enabled
When the operator lists jobs
Then all three jobs appear
And each is marked with its availability — local, enabled, or available
```

#### UC-JOS-2: Status shows last run, last outcome, and next due

```
Given a job that has run before and carries a schedule
When the operator requests job status
Then the job shows the last run time and the last run's outcome read from the runner's run state
And it shows the next due time derived from the job's schedule
```

#### UC-JOS-3: Status of a never-run job shows next due without last run

```
Given a configured job that has never run
When the operator requests job status
Then the job shows no last run and no last outcome
And it still shows a next due time derived from its schedule
```

#### UC-JOS-4: Enable a global job through the overlay

```
Given a global job available to the project but not enabled
When the operator enables the job
Then the project's enable overlay records the job as enabled
And the job appears as enabled on the next list
```

#### UC-JOS-5: Disable a global job through the overlay

```
Given a global job enabled in the project
When the operator disables the job
Then the project's enable overlay records the job as disabled
And the job no longer appears as enabled on the next list
```

#### UC-JOS-6: Enabling a non-global name is rejected without a write

```
Given a name that is not a global registry job — a local job or an unknown name
When the operator tries to enable or disable it
Then the command fails with an error naming the job
And no overlay entry is written
```

#### UC-JOS-7: Run a job on demand

```
Given a configured job
When the operator runs the job on demand
Then the job is dispatched through the existing run path
And the operator is told the run was accepted
```

## Known caveats

- The runtime status the surface shows is always the runner's recorded run state,
  read through the jobs HTTP API; the surface never recomputes or stores outcome,
  so its values track the runner exactly and add no second source of truth.
- The surface is scoped to the invoking project: list and status reflect that
  project's effective and available set, and enable/disable write that project's
  overlay. Cross-project operation is out of scope.
- The next-due time is a projection from the `when` schedule and the last run; it is
  advisory, not a guarantee — the host trigger fires on its own cadence and a job
  with an open run is not re-dispatched until its run closes.
