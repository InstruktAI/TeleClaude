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
correlated with the session holding the open run; a report from an earlier run
cannot close or alter its successor. Each procedure or script owns
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

#### UC-AJR-2: A late report cannot close or replace a successor run

#### UC-AJR-3: Checkpoint replacement is explicit

#### UC-AJR-4: Script results use the shared state contract

#### UC-AJR-5: A script receives its prior checkpoint

```gherkin
Given an operator has a scheduled script job that resumes from saved progress
And the job has a checkpoint for its project and declared identity
When the next run starts
Then the script receives that job's checkpoint and no other job's state
```

## Known caveats

- Checkpoint contents are opaque to the runtime. Each procedure or script defines
  its checkpoint content and resume rules.
- The report state is the latest value for one project and job, not an audit
  history of prior runs. Session transcripts remain the history.
