---
description: 'How to create a new agent or script job: artifacts, placement, validation.'
activation_trigger: Use when creating or changing a scheduled job — deciding script versus agent mode, placing its procedure, or wiring it into the job configuration.
visibility: 'public'
---

# Job Authoring — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## Goal

Create a new scheduled job with the correct artifacts in the correct locations,
validated by existing infrastructure.

## Preconditions

- The job's purpose is defined (what it does and why).
- The execution mode is known: **script** (direct Python execution) or **agent**
  (headless AI session that executes a procedure).

## Steps

### 1. Choose execution mode

| Mode     | When to use                                   | Artifacts needed                     |
| -------- | --------------------------------------------- | ------------------------------------ |
| `script` | Deterministic work that needs no AI reasoning | Script file + `teleclaude.yml` entry |
| `agent`  | Work requiring judgment, reading, or writing  | Procedure + `teleclaude.yml` entry   |

### 2. For agent jobs: write the procedure

The procedure is the job's entire mandate. The runner starts the agent with the
procedure's snippet ID, and the agent loads that procedure together with its
required-read closure in one pass (`telec docs get <id> --closure`). Nothing else
describes the job to the agent, so the procedure carries the whole workflow:
Goal, Preconditions, Steps, Outputs, Recovery.

Place it by the job's nature:

- Maintenance jobs: `docs/global/general/procedure/maintenance/{job-slug}.md`
- Domain-specific jobs: `docs/global/{domain}/procedure/{job-slug}.md`
- Project-only jobs: `docs/project/procedure/{job-slug}.md`

Add agent-job-hygiene as a required read so the closure delivers the run
discipline with the workflow. A job procedure carries no `activation_trigger`:
triggers belong to procedures an agent may invoke on its own judgment, and a job
procedure is executed by the runner.

Run `telec sync` before declaring the job, because the declaration's pointer is
resolved against the snippet index.

### 3. Register in teleclaude.yml

<!-- planned-change:generic-job-declarative-model -->

Add under `jobs:`:

```yaml
jobs:
  { job_key }:
    schedule: hourly | daily | weekly | monthly
    type: agent | script
    job: <procedure snippet id> # agent jobs only
    agent: claude | gemini | codex # agent jobs only
    thinking_mode: fast | med | slow # agent jobs only
    preferred_hour: 0..23 # optional, non-hourly
    preferred_weekday: 0..6 # optional, weekly
```

<!-- change:generic-job-declarative-model -->

Declare a job under `jobs:` with a `when` schedule and exactly one execution pointer — the
pointer present is the execution class, and there is no `type` field:

```yaml
jobs:
  { job_key }:
    when:
      at: '06:00' # or: every: 60m
    job: <procedure snippet id> # agent job — OR `script: jobs/{job_key}.py` for a script job
    agent: claude | gemini | codex # agent jobs only
    thinking_mode: fast | med | slow # agent jobs only
```

To publish a job for every project, declare it the same way under the `jobs:` registry in the
global `~/.teleclaude/teleclaude.yml`. A project then turns a global job on with an **enable
overlay** — a `jobs` entry carrying the same execution pointer and only `enabled: true` (or
`false` to turn it off); an overlay that carries any other field is rejected at config load.

<!-- /planned-change:generic-job-declarative-model -->

The `job:` value is the procedure's canonical snippet ID and is the agent job's
identity everywhere: dispatch, run state, the run directory, and the structured
report all use it. A global-registry declaration uses an ID that resolves from
every project (global-scope or slug-prefixed); a project-local declaration may
use its own `project/procedure/...` ID.

### 4. For script jobs: write the script

Place at `jobs/{job_slug}.py`. Define a `Job` subclass (`jobs/base.py`) whose `run()`
returns a `JobResult`, and expose it as a module-level `JOB` instance. The cron runner
imports the module and invokes `JOB.run()` in-process. Keep the PEP 723 dependency header
and a `if __name__ == "__main__": run_job_cli(JOB)` entrypoint so the script stays
runnable and debuggable standalone.

### 5. Sync and validate

Run `telec sync`. Validation checks:

- Snippet schema: required H2 sections per taxonomy type.
- Job config: schedule shape, execution pointer, and — for an agent job — that the
  `job:` pointer resolves to a delivered procedure snippet.

## Outputs

- Procedure (agent jobs only).
- `teleclaude.yml` entry.
- Script file (script jobs only).
- Successful `telec sync` with no validation errors.

## Recovery

- If `telec sync` fails, fix the reported issue and rerun.
- If validation reports the `job:` pointer as unknown, the procedure has not been
  indexed yet: sync the procedure first, then declare the job.
- If unsure about execution mode, default to agent — it can always be
  simplified to script later.
