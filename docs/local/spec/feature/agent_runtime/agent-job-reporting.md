---
description: Shared outcome and opaque checkpoint reporting for scheduled agent procedures
  and script jobs.
---

# Job Reporting — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md
- @docs/local/spec/domain/context-map.md

## What it is

Scheduled jobs produce an outcome and an optional checkpoint through one shared
reporting contract. Agent procedures submit through `telec jobs report`; script
jobs return their result to the runner, which uses the same state writer. The
runtime keeps the latest record for each project and job. Agent reports are
correlated with the session holding the open run. Each procedure or script owns
its checkpoint schema; the runtime stores its object without interpreting it.

## Canonical fields

### Outcome and checkpoint boundary

- Every accepted result updates the latest outcome for the job's project and
  declared identity. The runtime supplies execution identity from the run context.
- A supplied checkpoint object replaces the previous checkpoint in full. An
  explicit empty object clears it.
- An omitted checkpoint preserves the previous checkpoint. When none has been
  saved, it remains absent. Updating the outcome and applying this checkpoint
  decision is one atomic record replacement.
- Agent procedures use the optional `--state-json` object for replacement;
  script results use the same optional checkpoint contract. The reporting surface
  validates object shape, while checkpoint fields and resume rules belong to the
  job's brief or script contract.

### Use cases

#### UC-AJR-1: A report replaces the current project-job state

```gherkin
Given a scheduled agent job has an open run for project P and job J
When the agent reports its outcome and replacement checkpoint
Then the current state for P and J reflects the submitted outcome and checkpoint
And a later report replaces that state instead of adding another run-history record
```

#### UC-AJR-2: A late report cannot close or replace a successor run

```gherkin
Given an earlier run for project P and job J has stalled and a successor run is open
When the agent session belonging to the earlier run reports after the successor has opened
Then the successor remains open and its current state is unchanged
And only a report from the session holding the successor run can close it
```

#### UC-AJR-3: Checkpoint replacement is explicit

```gherkin
Scenario Outline: An outcome update carries an explicit checkpoint decision
Given an agent reporting a scheduled job has a saved checkpoint
When the agent submits an outcome with <checkpoint input>
Then the latest outcome reflects the submission
And the saved checkpoint is <checkpoint result>

Examples:
  | checkpoint input       | checkpoint result             |
  | no replacement         | the previous checkpoint       |
  | an empty object        | an empty object               |
  | a replacement object   | the submitted object in full  |
```

#### UC-AJR-4: Script results use the shared state contract

```gherkin
Given an agent inspecting the latest record for a scheduled script job
When that script job returns an outcome and replacement checkpoint
Then the agent sees the submitted outcome and checkpoint in that job's current record
And the checkpoint follows the same replacement contract as an agent procedure report
```

#### UC-AJR-5: A script receives its prior checkpoint

```gherkin
Given an agent inspecting the execution of a scheduled script job
And that job has a saved checkpoint for its project and declared identity
When the runner starts that script job
Then the agent observes that job's checkpoint in the supplied execution context
And a checkpoint from another project or job is not supplied
```

## Known caveats

- Checkpoint contents are opaque to the runtime. Each procedure or script defines
  its checkpoint content and resume rules.
- The report state is the latest value for one project and job, not an audit
  history of prior runs. Session transcripts remain the history.
