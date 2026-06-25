---
description: 'Scheduled job runner: architecture, generic closed-loop run lifecycle, job contract, and configuration surface.'
visibility: 'public'
---

# Jobs Runner — Design

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## Purpose

A standalone scheduled process that discovers and executes periodic jobs. Runs
independently from the daemon — jobs can be long-running, don't require daemon state,
and can be force-run manually via CLI.

The runner is the engine for all periodic automation: subscription maintenance, content
digests, GitHub issue triage, and future scheduled tasks.

One-off operations (e.g., initial YouTube subscription fetch during onboarding) live in
`scripts/` or `teleclaude/entrypoints/` and are invoked directly — they are not jobs.

### Philosophy

**Agents are supervisors, scripts are workers.** The agent owns the outcome: it runs the
existing functional scripts, watches what happens, fixes forward within its own scope if
something breaks, writes a run report, and reports a structured outcome that closes its
run. Scripts run in-process and return their outcome directly.

Agents do not reimplement script logic. The scripts already work — the agent's value is
resilience, error recovery, and auditability. See the Agent Job Hygiene procedure for the
full contract.

### The generic closed-loop run lifecycle

Both job classes flow through one run lifecycle with the same record, outcome, and
notification shape:

- A run is **opened** when the job is dispatched (`last_status="running"`,
  `run_started_at` set; agent runs also record `run_session_id`).
- A run is **closed** by the work with a real `JobResult` outcome — success or failure.
  A script job closes synchronously in the same tick; an agent job closes on a later tick
  when its structured outcome report arrives.
- A run that stays open past its expected window (`timeout`) is marked **stalled**.
- On every close or stall the runner emits a `job.run.*` event; an actionable outcome
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
teleclaude/cron/runner.py       Engine: config → discover → schedule check → execute
  │  ├── _load_job_schedules()  Read schedule config from teleclaude.yml
  │  ├── discover_jobs()        Read configured script jobs from teleclaude.yml
  │  ├── _dispatch_agent_job()  Open a run and fire-and-forget the agent session
  │  ├── _run_script_job()      Import the job module and invoke JOB.run() in-process
  │  ├── _sweep_open_runs()     Close agent runs from reported outcomes; stall the rest
  │  └── run_due_jobs()         Main loop: config → is_due() → open → run/sweep → close
  │
  ▼
teleclaude.yml                  Schedule configuration (frequency, timing, execution mode)
  │
  ├── script: jobs/foo.py       → In-process JOB.run() (no agent)
  └── job: foo                  → Agent session opened at dispatch, closed on report
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
agent session (fire-and-forget) tagged with the job name. The agent reads its spec doc
(`docs/project/spec/jobs/<job>.md`), does its work, fixes forward within scope, writes a
run report, and reports a structured outcome via `telec jobs report`. The runner's sweep
on a later tick reads that outcome and closes the run; a run never reported within its
window is stalled.

Agent jobs are daemon-independent for outcome reporting: the structured outcome is written
to the job's run directory on the local filesystem, so a run still closes when the daemon
is down.

#### Outcome reporting and notification

Outcomes ride the platform's existing event substrate. The runner emits a `job.run.*`
event on close or stall through `EventProducer`; the notification cartridge projects an
actionable event (failure or stall) to admins and stays silent for a clean run. The agent
never emits events — it reports only through `telec jobs report`, and the runner owns the
translation to events. When event emission cannot be delivered, the runner persists a
durable pending-emission record — the full payload keyed by `job_name` + `run_started_at` —
and the next sweep drains the queue, re-emitting each outcome exactly once until it
succeeds. A job with an unnotified actionable outcome is not re-dispatched, so a later run
cannot overwrite a notification that has not yet been delivered.

#### Components

| Component      | Path                                | Role                                                                             |
| -------------- | ----------------------------------- | -------------------------------------------------------------------------------- |
| CLI entry      | `scripts/cron_runner.py`            | Argument parsing, logging setup, invokes engine                                  |
| Engine         | `teleclaude/cron/runner.py`         | Config loading, discovery, schedule evaluation, run open/close/stall, event emit |
| State          | `teleclaude/cron/state.py`          | JSON persistence of the per-job run lifecycle                                    |
| Event schemas  | `teleclaude/events/schemas/jobs.py` | The `job.run.succeeded` / `job.run.failed` / `job.run.stalled` catalog entries   |
| Report wrapper | `telec jobs report`                 | The single structured-outcome channel an agent job uses to close its run         |
| Job base       | `jobs/base.py`                      | Abstract `Job` class, `JobResult`                                                |
| Job modules    | `jobs/*.py`                         | Concrete job implementations, each exposing a module-level `JOB`                 |

#### Cross-project iteration

Jobs that fan out across all registered projects (e.g., `log_bug_hunter`) do **not**
re-implement project discovery. They consume `ProjectCatalogService` (a lazy singleton
over `~/.teleclaude/projects.yaml`) and `ProjectJobOrchestrator` (a generic iterator that
runs an injected `run_for_project(node)` per subscribing project and isolates per-project
exceptions). Per-job services (e.g., `LogBugHunterService`) are one-project executors; the
cross-project loop lives in the orchestrator.

## Inputs/Outputs

**Inputs:**

- `teleclaude.yml` — schedule configuration for each registered job
- `jobs/*.py` — job modules discovered at runtime, each exposing a module-level `JOB`
- `~/.teleclaude/state/cron_state.json` — the per-job run lifecycle

**Outputs:**

- Job execution (side effects defined by each job)
- A `JobResult` outcome for every run, script and agent alike
- `job.run.*` events on close/stall, projected to a human when actionable
- Run reports at `~/.teleclaude/jobs/{job_name}/runs/{YYMMDD-HHMMSS}.md` (human-readable audit)
- Updated run lifecycle in `~/.teleclaude/state/cron_state.json`
- Structured logs to `/var/log/instrukt-ai/teleclaude/cron.log`

## Invariants

- Jobs are schedule-ignorant. They define `name` and `run()` only; scheduling lives in `teleclaude.yml`.
- A job without a `teleclaude.yml` entry is never invoked (except with `--force`).
- A job that has never run waits for its first scheduled occurrence after discovery.
- A run is opened at dispatch and closed only by a real outcome — dispatch never marks success.
- A job with an open run is not re-dispatched until its run closes or stalls.
- Both job classes produce the same `JobResult` outcome and `job.run.*` event shape.
- A clean run is silent; an actionable outcome (failure or stall) notifies a human.
- Agent jobs produce a run report and a structured outcome every run, even with nothing to process.

### Configuration surface

#### Project-level: `teleclaude.yml`

The project-root `teleclaude.yml` is the single source of truth for job scheduling. Each
job is registered under the `jobs:` key. Schedule fields: `schedule`
(`hourly`/`daily`/`weekly`/`monthly`), `preferred_hour` (0–23), `preferred_weekday` (0–6),
`preferred_day` (1–31). Execution-mode fields: `script` (path, in-process job), `job`
(spec doc name, agent job), `agent`, `thinking_mode`, `timeout` (seconds; default 1800).
`script` and `job` are mutually exclusive; `script` leads.

#### Per-person and global

`~/.teleclaude/people/{name}/teleclaude.yml` carries per-subscriber configuration;
`~/.teleclaude/teleclaude.yml` carries global scope. Discovery
(`teleclaude/cron/discovery.py`) scans both for subscribers of a given service.

## Primary flows

### Normal execution (5-minute host trigger)

1. Check pidfile at `~/.teleclaude/cron_runner.pid`; if another instance is alive, exit.
2. Write pidfile. Register cleanup via `atexit`.
3. `cron_runner.py` invokes `run_due_jobs()`.
4. Sweep open runs: close each agent run whose structured outcome has arrived (emit
   `job.run.succeeded`/`job.run.failed`); stall any open run past its `timeout` (emit
   `job.run.stalled`); re-attempt any closed-but-unnotified emission.
5. Load schedule config and discover configured script jobs.
6. For each due job not already open: open a run. A script job runs `JOB.run()` in-process
   on a daemon thread joined with `timeout`; if it times out, the runner records the failed
   outcome and aborts the rest of the pass so no later job starts. An agent job creates its
   session and stays open for the sweep; a session-creation failure records a failed outcome
   and emits `job.run.failed` rather than skipping silently.
7. Persist the run lifecycle after every transition.
8. Remove pidfile on exit (the daemon thread of any timed-out job is reaped here).

### Force run (CLI)

`cron_runner.py --force` bypasses schedule checks. Every discovered job runs regardless of
config or last run time, flowing the same open/close lifecycle.

### Manual run (API)

`POST /jobs/{name}/run` launches the standalone cron runner process
(`scripts/cron_runner.py --job NAME --force`) so the job executes in the ephemeral runner
process with the same timeout containment as a scheduled run. It opens a run and lets the
sweep close it; it does not report completion at dispatch and does not run job logic inside
the daemon. A spawn failure returns an explicit API error so the operator sees the start
failure synchronously.

### Script job contract

1. Create a Python module in `jobs/` exposing a `Job` subclass and a module-level `JOB`
   instance, with a PEP 723 header and a `run_job_cli(JOB)` `__main__` for standalone use.
2. Register in `teleclaude.yml` with `script` pointing to the module.

`JobResult` is the structured outcome both classes produce:

```python
@dataclass
class JobResult:
    success: bool
    message: str
    items_processed: int = 0
    errors: list[str] | None = None
```

### Agent job contract

1. Create a spec doc at `docs/project/spec/jobs/<name>.md`.
2. Register in `teleclaude.yml` with `job` pointing to the spec name.

The runner constructs the agent prompt from the `job` field and opens a session. The agent
loads its spec, does its work, writes a run report, reports its outcome via
`telec jobs report`, and stops. Follows the Agent Job Hygiene procedure.

### Schedule semantics

| Schedule | Minimum interval | Preferred timing                               |
| -------- | ---------------- | ---------------------------------------------- |
| hourly   | 1 hour           | —                                              |
| daily    | 20 hours         | `preferred_hour` (default 6)                   |
| weekly   | 6 days           | `preferred_weekday` (0=Mon) + `preferred_hour` |
| monthly  | 25 days          | `preferred_day` (1st) + `preferred_hour`       |

A job runs only when both conditions are met: minimum interval elapsed AND preferred timing
reached. Jobs that have never run wait for the first scheduled occurrence after discovery.

### Run lifecycle persistence

File: `~/.teleclaude/state/cron_state.json`

```json
{
  "jobs": {
    "job_name": {
      "first_seen_at": "2026-02-04T08:00:00+00:00",
      "run_started_at": null,
      "run_session_id": null,
      "last_run": "2026-02-04T08:00:35+00:00",
      "last_status": "success",
      "last_error": null
    }
  }
}
```

- `run_started_at` / `run_session_id`: set while a run is open (agent runs carry the session id).
- `last_run`: completion timestamp of the most recent closed run.
- `last_status`: `"running"` | `"success"` | `"failed"` | `"stalled"` | `"never"`.
- `last_error`: error or stall message, or null.

A separate `pending_emissions` collection holds undelivered actionable outcomes, each keyed
by `job_name` + `run_started_at` and carrying its full event payload, so a notification
survives a transport outage independent of later run state.

## Failure modes

- **Missing `teleclaude.yml`**: Engine logs a warning, no jobs run.
- **Job has no config entry**: Silently skipped (logged at debug level).
- **Job module fails to import**: Logged as error, run closed as failed, other jobs still run.
- **Script job raises during `run()`**: Caught, run closed as failed, other jobs still run.
- **Script job exceeds `timeout`**: The daemon-thread join records a failed `JobResult` and the runner aborts the rest of the pass so no later job runs concurrently; the hung job is hard-reaped when the runner process exits, freeing the pidlock, and the deferred jobs run on the next trigger.
- **A job cannot start**: An agent session-creation failure records a failed outcome and emits `job.run.failed`; an API runner-process spawn failure returns an explicit API error. A start failure is never a silent skip.
- **Agent run never reported within its window**: Marked `stalled`, emits `job.run.stalled`, notifies a human.
- **Event emission unavailable**: The outcome is persisted as a durable pending-emission record and re-emitted exactly once on a later sweep; the job is not re-dispatched until its actionable outcome is delivered, so it is never dropped or overwritten.
- **Overlap (concurrent runner instances)**: Second instance detects the pidfile and exits cleanly; stale pidfiles are detected and overwritten.
- **Daemon unavailable during an agent job**: The agent spawns without MCP tools and still reports its outcome to the filesystem; the run closes normally.

### Service integration

A host periodic trigger runs `scripts/cron_runner.py` every 5 minutes (macOS launchd
`ai.instrukt.teleclaude.cron`, `StartInterval 300`; systemd
`teleclaude-cron.service` + `.timer`, `OnUnitActiveSec=5min`). `bin/daemon-control.sh`
installs the trigger alongside the daemon on `start`/`restart`. Working directory: repo
root. Logs: `/var/log/instrukt-ai/teleclaude/cron.log`. Overlap prevention: pidfile at
`~/.teleclaude/cron_runner.pid`.

### CLI

```
cron_runner.py              Run all due jobs
cron_runner.py --force      Run all jobs regardless of schedule
cron_runner.py --job NAME   Run specific job only
cron_runner.py --dry-run    Check what would run without executing
cron_runner.py --list       List available jobs and their status
```

### Job specs

Each agent job has a spec document in `docs/project/spec/jobs/` describing what it does,
its files, configuration, and known issues. The spec is the agent's complete mandate.
