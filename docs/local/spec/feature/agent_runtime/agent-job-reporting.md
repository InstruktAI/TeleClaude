---
description: Structured outcome reporting and session correlation for scheduled agent jobs.
delivered_by:
  - job-run-state-single-file
---

# Agent Job Reporting — Spec

## What it is

Scheduled agent jobs submit their outcome and optional checkpoint through one
reporting operation. The runtime keeps the latest report state for each project
and job, and uses the reporting session identity to close the matching open run.
The job procedure owns the meaning of its checkpoint; the runtime stores that
value without interpreting it.

## Canonical fields

### Use cases

<!-- planned:job-run-state-single-file -->

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
When the earlier run reports after the successor has opened
Then the successor remains open and its current state is unchanged
And only a report from the session holding the successor run can close it
```

<!-- /planned:job-run-state-single-file -->

## Known caveats

- Checkpoint contents are opaque to the runtime. Each job procedure defines the
  content it reads and submits.
- The report state is the latest value for one project and job, not an audit
  history of prior runs. Session transcripts remain the history.
