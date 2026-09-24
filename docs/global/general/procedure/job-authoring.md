---
description: 'How to create a new agent or script job: artifacts, placement, validation.'
activation_trigger: Use when creating or changing a scheduled job — deciding script versus agent mode, placing its procedure, or wiring it into the job configuration.
visibility: 'public'
---

# Job Authoring — Procedure

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

The procedure defines the job's task. The runner starts the agent with the
procedure's snippet ID, and the agent loads that procedure together with its
required-read closure in one pass (`telec docs get <id> --closure`). The procedure
carries the whole task workflow:
Goal, Preconditions, Steps, Outputs, Recovery.

Place it by the job's nature:

- Maintenance jobs: `docs/global/general/procedure/maintenance/{job-slug}.md`
- Domain-specific jobs: `docs/global/{domain}/procedure/{job-slug}.md`
- Project-only jobs: `docs/project/procedure/{job-slug}.md`

Define the job-specific artifacts and report under Outputs, including any history
the next run consumes. The `next-run-job` brief supplies the role boundary and
structured outcome submission. A job procedure carries no `activation_trigger`:
triggers belong to procedures an agent may invoke on its own judgment, and a job
procedure is executed by the runner.

The declaration's pointer is resolved against the owning publisher's snippet
source tree, so the procedure file only needs to exist at its taxonomy path
before the declaration is validated.

### 3. Register in teleclaude.yml

Declare a job as an entry of the `jobs:` list with a `when` schedule and exactly one execution
pointer — the pointer present is the execution class and the job's identity; there is no name
key and no `type` field:

```yaml
jobs:
  - when:
      at: '06:00' # or: every: 60m
    job: <procedure snippet id> # agent job — OR `script: jobs/{job_slug}.py` for a script job
    agent: [claude, codex, gemini] # agent jobs only: ordered preference, resolved through availability
    thinking_mode: fast | med | slow # agent jobs only
```

To publish a job for every project, declare it the same way in the `jobs:` registry list of
the global `~/.teleclaude/teleclaude.yml`. A project gets nothing by default; it
**subscribes** with a `jobs` entry carrying the same execution pointer, and that entry may
override any setting for that project — its own `when`, `agent`, `thinking_mode`, `timeout` —
or set `enabled: false` to unsubscribe. Whatever it leaves unset falls back to the published
defaults, and the job runs inside the subscribing project.

The `job:` value is the procedure's canonical snippet ID and is the agent job's
identity everywhere: dispatch, run state, the run directory, and the structured
report all use it. A global-registry declaration uses an ID that resolves from
every project (global-scope or slug-prefixed); a project-local declaration may
use its own `project/procedure/...` ID.

### 4. For script jobs: write the script

The module's stem is the script job's identity in run state, the run directory, and the runner's job filter.

Place at `jobs/{job_slug}.py`. Define a `Job` subclass (`jobs/base.py`) whose
`run(context)` returns a `JobResult`, and expose it as a module-level `JOB` instance. The
cron runner imports the module and invokes `JOB.run(context)` in-process, passing the
project the run belongs to — its root and slug — so one published module serves every
subscribing project. Keep the PEP 723 dependency header and a
`if __name__ == "__main__": run_job_cli(JOB)` entrypoint so the script stays runnable and
debuggable standalone.

### 5. Validate

Commit the change. The commit gate validates:

- Snippet schema: required H2 sections per taxonomy type.
- Job config: schedule shape, execution pointer, and — for an agent job — that the
  `job:` pointer resolves to a delivered procedure snippet.

A declaration authored in the global registry is validated through a project that
subscribes its execution pointer, where the effective set resolves the published
declaration onto that project's own: commit from that project root and let its
publication run. The global registry root is not a publication target, so
publication there validates nothing.

## Outputs

- Procedure (agent jobs only).
- `teleclaude.yml` entry.
- Script file (script jobs only).
- A commit-gate run reporting no validation findings.

## Recovery

- If the commit gate reports findings, fix the reported issue and rerun `telec code commit`.
- If validation reports the `job:` pointer as unknown, the procedure is missing
  from its publisher source tree: confirm the file exists at the taxonomy path
  the pointer names, that its snippet type is `procedure`, and that it carries no
  `delivered_by`.
- If unsure about execution mode, default to agent — it can always be
  simplified to script later.
