---
description: 'Scheduled job runner: architecture, generic closed-loop run lifecycle, job contract, and configuration surface.'
visibility: 'public'
---

# Jobs Runner — Design

## Purpose

A standalone scheduled process that discovers and executes periodic jobs. Runs
independently from the daemon — jobs can be long-running, don't require daemon state,
and can be force-run manually via CLI.

The runner is the engine for all periodic automation: subscription maintenance, content
digests, GitHub issue triage, and future scheduled tasks.

One-off operations (e.g., initial YouTube subscription fetch during onboarding) live in
`scripts/` or `teleclaude/entrypoints/` and are invoked directly — they are not jobs.

### Execution ownership

An agent job executes the procedure named by its declaration. That procedure owns
the task, its artifacts, and its recovery steps; the `run-job` brief binds
the job role and submits its structured outcome. A script job runs in-process
and returns its outcome directly. Scheduling, dispatch, and outcome notification
belong to the runner.

### The generic closed-loop run lifecycle

Both job classes flow through one run lifecycle with the same record, outcome, and
notification shape:

- A run is **opened** when the job is dispatched (`last_status="running"`,
  `run_started_at` set; agent runs also record `run_session_id`).
- A run is **closed** by the work with a real `JobResult` outcome — success or failure.
  A script job closes synchronously in the same tick; an agent job closes on a later tick
  when its structured outcome report arrives.
- A run that stays open past its expected window (`timeout`) is marked **stalled**.
- On every close or stall the runner emits a job-run outcome event; an actionable outcome
  (failure or stall) notifies a human through the notification cartridge, a clean run is
  silent. "Dispatched" never means "succeeded."

### Architecture

```
host trigger (launchd StartInterval 300s / systemd timer, every 5 min)
  │
  ├── pidfile check (~/.teleclaude/cron_runner.pid)
  │   └── If another instance running → exit cleanly
  │
  ▼
scripts/cron_runner.py          CLI entry point
  │
  ▼
teleclaude/cron/runner.py       Engine: effective jobs → schedule check → execute
  │  ├── config.jobs.load_effective_jobs()  Compose each project's jobs
  │  ├── _dispatch_agent_job()  Open a run and fire-and-forget the agent session
  │  ├── _run_script_job()      Import the job module and invoke JOB.run() in-process
  │  ├── _run_pre_dispatch_sweeps()  Close reported runs; stall timed-out runs
  │  └── run_due_jobs()         Main loop: config → is_due() → open → run/sweep → close
  │
  ▼
teleclaude.yml                  Schedule configuration (frequency, timing, execution mode)
  │
  ├── script: jobs/foo.py       → In-process JOB.run() (no agent)
  └── job: <procedure id>       → Agent session opened at dispatch, closed on report
  │
  ▼
~/.teleclaude/state/cron_state.json   Per-job run lifecycle (run_started_at, status, outcome)
```

#### Execution modes

The `script` field is the discriminator. Its presence determines the execution mode:

| Mode        | Function               | Characteristics                                                                         |
| ----------- | ---------------------- | --------------------------------------------------------------------------------------- |
| Script jobs | in-process `JOB.run()` | The runner imports the job module and calls its `JOB` instance, returning a `JobResult` |
| Agent jobs  | session at dispatch    | Full agent session with tools + MCP; opens a run, closes on reported outcome            |

**Script jobs** (`script` present) — The runner resolves the configured module, imports
it, reads its module-level `JOB` instance, and calls `JOB.run()` in-process on a daemon
worker thread joined with the job's `timeout`. The returned `JobResult` closes the run in
the same tick. On timeout the runner records a failed `JobResult` and releases the tick; the
daemon thread cannot keep the process alive, so a hung job is hard-reaped when the runner
process exits at end of pass, releasing the pidlock for the next trigger. No subprocess is
spawned and no stdout is parsed.

**Agent jobs** (`script` absent, `job` required) — The runner opens a run and creates an
agent session (fire-and-forget) for the job's declared name; the session executes the
procedure snippet ID in `job`.

The name is the job's identity everywhere: the dispatch argument, the run state key, the per-job state file path, and the report key.

The agent loads the procedure with its required-read closure and executes its task. When it needs prior job-owned state, it reads the checkpoint from the latest record at `STATE_DIR/runs/<project_slug>/<job_name>.json`. It submits its outcome and any replacement checkpoint through `telec jobs report <name> ... --state-json '<object>'`. The command and the script-result adapter use one state writer under the checkpoint-update contract in `local/projects/teleclaude/spec/feature/agent_runtime/agent-job-reporting`. The runner reads the same record and closes only the open run whose session identity matches the report. A late report cannot close or replace a successor's result; a run with no matching report within its window is stalled.

Agent jobs are daemon-independent for outcome reporting: `telec jobs report` writes the latest outcome and job-owned state to the local filesystem, so a run still closes when the daemon is down.

#### Outcome reporting and notification

Outcomes ride the platform's existing event substrate. The runner emits a job-run outcome
event on close or stall through `EventProducer`; the notification cartridge projects an
actionable event (failure or stall) to admins and stays silent for a clean run. The agent
never emits events — it reports only through `telec jobs report`, and the runner owns the
translation to events. When event emission cannot be delivered, the runner persists a
durable pending-emission record — the full payload keyed by the run's project, job identity,
and `run_started_at` — and the next sweep drains the queue, re-emitting each outcome exactly
once until it succeeds. A job with an unnotified actionable outcome is not re-dispatched in
that project, so a later run cannot overwrite a notification that has not yet been delivered.

#### Components

| Component      | Path                                | Role                                                                         |
| -------------- | ----------------------------------- | ---------------------------------------------------------------------------- |
| CLI entry      | `scripts/cron_runner.py`            | Argument parsing, logging setup, invokes engine                              |
| Engine         | `teleclaude/cron/runner.py`         | Effective-set loading, schedule evaluation, run open/close/stall, event emit |
| State          | `teleclaude/cron/state.py`          | JSON persistence of the per-job run lifecycle                                |
| Event schemas  | `teleclaude/events/schemas/jobs.py` | The succeeded, failed and stalled job-run catalog entries                    |
| Report wrapper | `telec jobs report`                 | The single structured-outcome channel an agent job uses to close its run     |
| Job base       | `jobs/base.py`                      | Abstract `Job` class, `JobResult`                                            |
| Job modules    | `jobs/*.py`                         | Concrete job implementations, each exposing a module-level `JOB`             |

#### Cross-project iteration

The runner itself walks every registered project (`ProjectCatalogService`, a lazy singleton
over `~/.teleclaude/projects.yaml`), composes that project's effective job set, and runs what
is due there. A job never iterates projects, and no job carries a dedicated
per-project executor: the runner dispatches every job through its declared
execution class for the project in hand. A failure in one project is isolated
and the walk continues.

## Inputs/Outputs

**Inputs:**

- the global `~/.teleclaude/teleclaude.yml` registry and every registered project's `teleclaude.yml` — published jobs, subscriptions, and local declarations
- `jobs/*.py` — script-pointer targets imported for effective script jobs, each exposing a module-level `JOB`
- `~/.teleclaude/state/cron_state.json` — the run lifecycle, per project and job

**Outputs:**

- Job execution (side effects defined by each job)
- A `JobResult` outcome for every run, script and agent alike
- Job-run outcome events on close/stall, projected to a human when actionable

- The latest per-job outcome/checkpoint record at `STATE_DIR/runs/<project_slug>/<job_name>.json`, shared by script results and agent reports. Each accepted outcome atomically updates the record under the checkpoint replacement/preservation contract in `local/projects/teleclaude/spec/feature/agent_runtime/agent-job-reporting`. The JSON contains the structured outcome and optional opaque job-owned state; per-run report history is not accumulated.

- Updated run lifecycle in `~/.teleclaude/state/cron_state.json`, per project and job

- Structured logs to `~/.local/state/instrukt-ai/teleclaude/cron.log`

## Invariants

- Jobs are schedule-ignorant and name-ignorant. A job module defines `run()` only; its name and schedule live in its `teleclaude.yml` declaration.
- A job without a `teleclaude.yml` entry is never invoked (except with `--force`).
- A job that has never run waits for its first scheduled occurrence after discovery.
- A run is opened at dispatch and closed only by a real outcome — dispatch never marks success.
- A job with an open run is not re-dispatched until its run closes or stalls.
- Both job classes produce the same `JobResult` outcome and job-run outcome event shape.
- A clean run is silent; an actionable outcome (failure or stall) notifies a human.

- Both job classes produce one structured outcome every run, including an empty successful run. Script returns and agent reports use the same current-record writer. A job's procedure or script owns its checkpoint schema; the runner persists the opaque payload under the shared reporting contract.
- A job has one identity, the `name` its declaration carries. Dispatch, run state, the per-job state path, the report key, the runner's job filter, and the jobs API all use that name, and nothing derives another identity from the execution pointer.

### Configuration surface

#### Project-level: `teleclaude.yml`

The project-root `teleclaude.yml` registers a project's jobs as a list under the `jobs:` key.
Every entry carries a required `name` (lowercase kebab-case), which is the job's identity
(see `local/projects/teleclaude/spec/feature/config/job-declaration-model`). A job declares WHEN it runs
through the `when` block (see `local/projects/teleclaude/spec/feature/config/job-schedule-contract`) and WHAT
it runs through exactly one execution pointer — `script` (path, in-process job) or `job`
(procedure snippet ID, agent job). The pointer present IS the execution class; there is no
separate discriminator field. The remaining execution fields are `agent` (a non-empty ordered
preference list the run boundary hands to automatic dispatch), `thinking_mode`, and `timeout`
(seconds; default 1800).

A project `jobs` entry that carries the name of a published global job is a
**subscription**: it turns the global job on for this project (`enabled`, default on) and
overrides whatever else it sets — `when`, `agent`, `thinking_mode`, `timeout`, `category` —
falling back to the published defaults for the rest, including the execution pointer.
Nothing validates what a project may override except the pointer, which a subscription
cannot change; the job runs in that project alone. An entry whose name is not in the global
registry is a local job declaration (a name, exactly one pointer, and a `when` schedule).

A job's candidate order comes only from its effective declaration. A one-entry list
uses the same selection path as any other list; exhaustion fails the run with the
selection refusal reason. The command matrix supplies no job candidate defaults.

A project's effective job set is composed once by the configuration context — local
declarations plus the published jobs it subscribes to, each overlaid by its subscribing entry
— and every consumer (the runner, the run boundary, the jobs API, and the report CLI) reads
that composed set rather than raw entries.

#### Global registry and per-person scope

`~/.teleclaude/teleclaude.yml` carries global scope, including the `jobs:` **registry** of
published jobs available to every project; a project runs a published job only by subscribing
to it. `~/.teleclaude/people/{name}/teleclaude.yml` carries per-subscriber configuration.
Discovery (`teleclaude/cron/discovery.py`) scans both for subscribers of a given service.

## Primary flows

### Normal execution (5-minute host trigger)

1. Check pidfile at `~/.teleclaude/cron_runner.pid`; if another instance is alive, exit.
2. Write pidfile. Register cleanup via `atexit`.
3. `cron_runner.py` invokes `run_due_jobs()`.
4. Sweep open runs: close each agent run whose structured outcome has arrived (emit
   the job-run succeeded or failed event); stall any open run past its `timeout` (emit
   the job-run stalled event); re-attempt any closed-but-unnotified emission.
5. Compose each registered project's effective job set through `load_effective_jobs`, including its local declarations and subscribed global jobs.
6. For each due job not already open: open a run. A script job runs `JOB.run()` in-process
   on a daemon thread joined with `timeout`; if it times out, the runner records the failed
   outcome and aborts the rest of the pass so no later job starts. An agent job creates its
   session and stays open for the sweep; a session-creation failure records a failed outcome
   and emits the job-run failed event rather than skipping silently.
7. Persist the run lifecycle after every transition.
8. Remove pidfile on exit (the daemon thread of any timed-out job is reaped here).

### Force run (CLI)

`cron_runner.py --force` bypasses schedule checks for the selected project's effective
jobs, while retaining the same open/close lifecycle and active-run safeguards.

### Manual run (API)

`POST /jobs/{name}/run` launches the standalone cron runner for the named job.
Its optional `project` query parameter selects the registered project; omission
selects the runner's own project. The cron command receives the same project
selection and resolves that project's effective declaration. Acceptance records
dispatch, and the run closes through its normal outcome path. A spawn failure
returns an explicit API error.

### Script job contract

1. Create a Python module in `jobs/` exposing a `Job` subclass and a module-level `JOB`
   instance, with a PEP 723 header and a `run_job_cli(JOB)` `__main__` for standalone use.
2. Register in `teleclaude.yml` with a `name` and `script` pointing to the module.

`JOB.run(context)` receives its project's root and slug and its previous opaque
checkpoint when present. The runner resolves the current record from the
effective declaration and supplies that checkpoint; the job's script contract
defines how to resume from it. A published module serves each subscribing project
without resolving its own job identity or reading an ambient working directory.
Global modules live in the mother repository; local modules live in the declaring
project.

`JobResult` is the shared outcome envelope defined by `jobs/base.py`. A script
returns its outcome and optional replacement checkpoint to the runner. The runner
uses the same current-record writer as the agent-report CLI, then closes the
script run through its existing outcome lifecycle. Checkpoint update semantics
belong to `local/projects/teleclaude/spec/feature/agent_runtime/agent-job-reporting`;
checkpoint meaning belongs to the job's procedure or script.

### Agent job contract

1. Write the job's procedure (see the Job Authoring procedure), including its
   outputs and recovery, and sync it so its ID resolves.
2. Register in `teleclaude.yml` with a `name` and `job` carrying the procedure's snippet ID.

The runner dispatches `/run-job <name>` through the canonical command-session contract,
rooted at the project the run belongs to, and opens a run keyed by that project and name. The
run boundary gives the session both the job's name and the procedure its declaration points
at.

The agent loads the procedure with its required-read closure, does its work, reads the latest checkpoint when needed, and submits the outcome through one `telec jobs report <name> --success <true|false> --message '<summary>' [--state-json '<object>']` call. The optional object follows the shared checkpoint-update contract in `local/projects/teleclaude/spec/feature/agent_runtime/agent-job-reporting`. The CLI writes the current record at `STATE_DIR/runs/<project_slug>/<job_name>.json`; the agent does not write it directly. It then stops.

An agent outcome carries the reporting session's identity as well as the project
and job. The sweep closes only the run opened for that session; a late outcome
from an earlier run cannot close its successor.

### Schedule semantics

A job runs on the cadence declared in its `when` block — an interval (`every`, e.g.
`60m`/`2h`/`1d`) or one or more wall-clock times (`at`, optionally filtered by `weekdays`).
Exactly one of `every`/`at` is set. The full scheduling contract is
`local/projects/teleclaude/spec/feature/config/job-schedule-contract`. Jobs that have never run wait for the
first scheduled occurrence after discovery.

### Run lifecycle persistence

Migration derives project association from recorded execution context and typed
session identity. Parent fan-out outcomes remain dispatch history; they never
become successful project scans. Ambiguous history stays recoverable, and an
active or queued outcome whose ownership cannot be resolved stops migration
without discarding its original record.

File: `~/.teleclaude/state/cron_state.json`

Entries are keyed by project slug and job name, so the same published job carries separate
lifecycles in every project that subscribes to it. A job reads only the entry under its own
name: an entry whose key names no job in the project's effective set is inert — no job reads,
closes, or reports it — and a job with no entry under its name starts fresh, waiting for its
first scheduled occurrence. Renaming a job therefore starts its history anew; nothing carries
an entry across a rename or an identity change.

```json
{
  "jobs": {
    "<project slug>": {
      "<job identity>": {
        "first_seen_at": "2026-02-04T08:00:00+00:00",
        "run_started_at": null,
        "run_session_id": null,
        "last_run": "2026-02-04T08:00:35+00:00",
        "last_status": "success",
        "last_error": null
      }
    }
  }
}
```

- `run_started_at` / `run_session_id`: set while a run is open (agent runs carry the session id).
- `last_run`: completion timestamp of the most recent closed run.
- `last_status`: `"running"` | `"success"` | `"failed"` | `"stalled"` | `"never"`.
- `last_error`: error or stall message, or null.

A separate `pending_emissions` collection holds undelivered actionable outcomes, each keyed
by the run's project, job identity, and `run_started_at`, and carrying its full event
payload, so a notification survives a transport outage independent of later run state. The
payload carries `job_key` — the project and identity joined — which is the field the
notification lifecycle groups an outcome under, so two projects running one published job
keep separate notification lifecycles.

## Failure modes

- **Missing `teleclaude.yml`**: Engine logs a warning, no jobs run.
- **Job has no config entry**: Silently skipped (logged at debug level).
- **Job module fails to import**: Logged as error, run closed as failed, other jobs still run.
- **Script job raises during `run()`**: Caught, run closed as failed, other jobs still run.
- **Script job exceeds `timeout`**: The daemon-thread join records a failed `JobResult` and the runner aborts the rest of the pass so no later job runs concurrently; the hung job is hard-reaped when the runner process exits, freeing the pidlock, and the deferred jobs run on the next trigger.
- **A job cannot start**: An agent session-creation failure — including an agent preference list with no eligible candidate — records a failed outcome carrying the dispatch refusal reason and emits the job-run failed event; an API runner-process spawn failure returns an explicit API error. A start failure is never a silent skip.
- **Agent run never reported within its window**: Marked `stalled`, emits the job-run stalled event, notifies a human.
- **Event emission unavailable**: The outcome is persisted as a durable pending-emission record and re-emitted exactly once on a later sweep; the job is not re-dispatched until its actionable outcome is delivered, so it is never dropped or overwritten.
- **Overlap (concurrent runner instances)**: Second instance detects the pidfile and exits cleanly; stale pidfiles are detected and overwritten.
- **Daemon unavailable during an agent job**: The agent spawns without MCP tools and still reports its outcome to the filesystem; the run closes normally.

### Service integration

A host periodic trigger runs `scripts/cron_runner.py` every 5 minutes (macOS launchd
`ai.instrukt.teleclaude.cron`, `StartInterval 300`; systemd
`teleclaude-cron.service` + `.timer`, `OnUnitActiveSec=5min`). `bin/daemon-control.sh`
installs the trigger alongside the daemon on `start`/`restart`. Working directory: repo
root; each project's jobs run rooted at that project. Logs:
`~/.local/state/instrukt-ai/teleclaude/cron.log`. Overlap prevention: pidfile at
`~/.teleclaude/cron_runner.pid`.

### CLI

```
cron_runner.py              Run all due jobs
cron_runner.py --force      Run all jobs regardless of schedule
cron_runner.py --job NAME   Run specific job only
cron_runner.py --dry-run    Check what would run without executing
cron_runner.py --list       List available jobs and their status
```

### Job procedures

An agent job's complete mandate is the procedure its `job` pointer names. There is no
separate job document: the procedure carries the workflow and its dependencies;
the `run-job` brief supplies the job-role boundary and structured close-out.
