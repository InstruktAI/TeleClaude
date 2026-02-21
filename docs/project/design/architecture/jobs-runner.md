---
description: 'Scheduled job runner: architecture, job contract, and configuration surface.'
id: 'project/design/architecture/jobs-runner'
scope: 'project'
type: 'design'
---

# Jobs Runner — Design

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## Purpose

A standalone scheduled process that discovers and executes periodic jobs.
Runs independently from the daemon — jobs can be long-running, don't require daemon
state, and can be force-run manually via CLI.

The runner is the engine for all periodic automation: subscription maintenance,
content digests, GitHub issue triage, and future scheduled tasks.

One-off operations (e.g., initial YouTube subscription fetch during onboarding)
live in `scripts/` or `teleclaude/entrypoints/` and are invoked directly — they
are not jobs.

## Philosophy

**Agents are supervisors, scripts are workers.** The target architecture is for all
jobs to be agent-supervised. The agent owns the outcome: it runs the existing
functional scripts, watches what happens, fixes forward within its own scope if
something breaks, and writes a run report.

Agents do not reimplement script logic. The scripts already work — the agent's
value is resilience, error recovery, and auditability. An agent can reason about
why a script failed and attempt a scoped fix (its own job scripts and data only).
If the issue is outside its scope, it records the failure and moves on.

See the Agent Job Hygiene procedure for the full contract.

## Architecture

```
launchd (every 5 minutes)
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
  │  ├── discover_jobs()        Dynamic import of jobs/*.py (python-type jobs)
  │  ├── _run_agent_job()       Spawn agent subprocess (agent-type jobs)
  │  ├── _is_due()              Evaluate schedule against last run timestamp
  │  └── run_due_jobs()         Main loop: config → is_due() → run/spawn → mark state
  │
  ▼
teleclaude.yml                  Schedule configuration (frequency, timing, execution mode)
  │
  ├── script: jobs/foo.py       → Direct execution via run() (no agent)
  └── job: foo                  → Agent subprocess via run_job() (full tools + MCP)
  │
  ▼
~/.teleclaude/cron_state.json   Persistent state (last_run, status, errors)
```

### Execution Modes

The `script` field is the discriminator. Its presence determines the execution mode:

| Mode           | Function     | Characteristics                                                   |
| -------------- | ------------ | ----------------------------------------------------------------- |
| Script jobs    | `job.run()`  | Direct Python execution, no agent, returns `JobResult`            |
| Agent jobs     | `run_job()`  | Full interactive subprocess with tools + MCP, role-aware          |
| One-shot calls | `run_once()` | Lobotomized JSON-only invocation, no tools, no MCP (not for jobs) |

**Script jobs** (`script` present) — The runner executes the script directly. No
agent is involved. Use for simple, deterministic jobs that need no AI reasoning.

**Agent jobs** (`script` absent, `job` required) — The runner spawns a subprocess
via `run_job()`. This utilizes the standardized `teleclaude/helpers/agent_cli.py`
library (Elevated mode). The agent has full tool access (bash, read, write, glob, grep,
etc.) and MCP access when the daemon is running. The agent reads its spec doc
(`docs/project/spec/jobs/<job>.md`), runs whatever scripts and tools the spec
describes, fixes forward within scope, writes a run report, and stops.

See: [Agent Invocation Modes](@general/concept/agent-invocation-modes)

Agent jobs are daemon-independent: they run as direct subprocesses, not as daemon
API calls. If the daemon is down, the agent still spawns and executes — it just
lacks MCP tools (teleclaude\_\_\*), which is acceptable degradation for filesystem-
based jobs.

**One-shot calls** (`run_once()`) are unrelated to the job runner. They are
lobotomized invocations for structured JSON output (e.g., YouTube tagging) with
no tool or MCP access.

### Role Resolution

Agent jobs accept a `role` parameter that propagates to the subprocess environment
via `TELECLAUDE_JOB_ROLE`. The MCP wrapper reads this for tool filtering.

Resolution chain:

1. Daemon available → resolve role from config (future: person-identity-auth)
2. Daemon unavailable → silently default to `admin`

No warnings are emitted for daemon unavailability. The fallback is silent because
other runners (log-bug-hunter) monitor daemon health.

### Components

| Component   | Path                           | Role                                                               |
| ----------- | ------------------------------ | ------------------------------------------------------------------ |
| CLI entry   | `scripts/cron_runner.py`       | Argument parsing, logging setup, invokes engine                    |
| Engine      | `teleclaude/cron/runner.py`    | Config loading, job discovery, schedule evaluation, execution loop |
| State       | `teleclaude/cron/state.py`     | JSON persistence of per-job run history                            |
| Discovery   | `teleclaude/cron/discovery.py` | Config-driven subscriber discovery for jobs                        |
| Job base    | `jobs/base.py`                 | Abstract `Job` class, `JobResult`                                  |
| Job modules | `jobs/*.py`                    | Concrete job implementations                                       |

## Inputs/Outputs

**Inputs:**

- `teleclaude.yml` — schedule configuration for each registered job
- `jobs/*.py` — job modules discovered at runtime
- `~/.teleclaude/cron_state.json` — last run timestamps

**Outputs:**

- Job execution (side effects defined by each job)
- `JobResult` with structured success/failure data (script jobs)
- Run reports at `~/.teleclaude/jobs/{job_name}/runs/{YYMMDD-HHMMSS}.md` (agent jobs)
- Updated state in `cron_state.json`
- Structured logs to `/var/log/instrukt-ai/teleclaude/cron.log`

## Invariants

- Jobs are schedule-ignorant. They define `name` and `run()` only. All scheduling
  configuration lives in `teleclaude.yml`.
- A job without a `teleclaude.yml` entry is never invoked (except with `--force`).
- A job that has never run executes immediately on first discovery.
- State is persisted after every job execution, success or failure.
- Agent jobs produce a run report every run, even when there is nothing to process.
- Agent jobs fix forward within scope; they do not chase out-of-scope issues.

## Configuration Surface

### Project-level: `teleclaude.yml`

The `teleclaude.yml` at the project root is the single source of truth for job
scheduling. Each job is registered under the `jobs:` key with its schedule
configuration:

```yaml
jobs:
  youtube_sync_subscriptions:
    schedule: daily
    preferred_hour: 6
```

#### Schedule fields

| Field               | Type       | Default  | Description                                       |
| ------------------- | ---------- | -------- | ------------------------------------------------- |
| `schedule`          | string     | required | Frequency: `hourly`, `daily`, `weekly`, `monthly` |
| `preferred_hour`    | int (0–23) | 6        | Hour of day to run (daily/weekly/monthly)         |
| `preferred_weekday` | int (0–6)  | 0        | Day of week (0=Mon, weekly only)                  |
| `preferred_day`     | int (1–31) | 1        | Day of month (monthly only)                       |

#### Execution mode fields

| Field           | Type   | Default  | Description                                                  |
| --------------- | ------ | -------- | ------------------------------------------------------------ |
| `script`        | string | (none)   | Path to script for direct execution (no agent)               |
| `job`           | string | (none)   | Spec doc name, resolves to `docs/project/spec/jobs/<job>.md` |
| `agent`         | string | `claude` | AI agent to use (`claude`, `gemini`, `codex`)                |
| `thinking_mode` | string | `fast`   | Model tier (`fast`, `med`, `slow`)                           |
| `timeout`       | int    | (none)   | Per-job timeout in seconds (default: 1800 for agent jobs)    |

`script` and `job` are mutually exclusive. `script` is leading: if present, the
job runs directly without an agent. If absent, `job` is required and the runner
spawns an agent session.

To add a script job, create the script AND register in `teleclaude.yml` with `script`.
To add an agent job, create a spec doc AND register in `teleclaude.yml` with `job`.

### Per-person: `~/.teleclaude/people/{name}/teleclaude.yml`

Person-scoped configuration for jobs that operate per-subscriber:

```yaml
subscriptions:
  youtube: youtube.csv # Relative to subscriptions/ dir
interests:
  - ai
  - devtools
  - geopolitics
```

Discovery (`teleclaude/cron/discovery.py`) scans `~/.teleclaude/people/*/teleclaude.yml`
to find subscribers for a given service.

### Global: `~/.teleclaude/teleclaude.yml`

Global scope (people list, ops users). Also checked by discovery for global-level
subscriptions.

## Primary Flows

### Normal execution (5-minute launchd trigger)

1. Check pidfile at `~/.teleclaude/cron_runner.pid`. If another instance is alive, exit.
2. Write pidfile. Register cleanup via `atexit`.
3. `cron_runner.py` invokes `run_due_jobs()`.
4. Engine loads schedule config from `teleclaude.yml`.
5. Engine discovers job modules from `jobs/*.py`.
6. For each job with a config entry: load last run from state, evaluate `_is_due()`.
7. If due: call `job.run()` (script) or `run_job()` (agent subprocess), persist result.
8. Jobs without config entries are silently skipped.
9. Remove pidfile on exit.

### Force run (CLI)

`cron_runner.py --force` bypasses all schedule checks. Every discovered job runs
regardless of config or last run time.

## Job Contract

### Script jobs

Direct execution, no agent. For simple, deterministic work.

1. Create a Python module in `jobs/` that subclasses `Job` and exports a `JOB` instance
2. Register in `teleclaude.yml` with `script` pointing to the module

```yaml
jobs:
  simple_reminder:
    schedule: hourly
    script: jobs/simple_reminder.py
```

Script jobs return a `JobResult` — the structured output contract that the runner
uses for logging and state persistence:

```python
@dataclass
class JobResult:
    success: bool
    message: str
    items_processed: int = 0
    errors: list[str] | None = None
```

The runner logs `message`, `items_processed`, and `errors` from the result and
persists `success`/`message` to `cron_state.json`.

### Agent jobs

The agent is a supervisor — it reads its spec doc, runs the tools and scripts
described in the spec, fixes forward within scope, writes a run report, and stops.
Follows the Agent Job Hygiene procedure.

1. Create a spec doc at `docs/project/spec/jobs/<name>.md`
2. Register in `teleclaude.yml` with `job` pointing to the spec name

```yaml
jobs:
  memory_review:
    schedule: weekly
    preferred_weekday: 0
    preferred_hour: 8
    job: memory-review
    agent: claude
    thinking_mode: fast

  youtube_sync_subscriptions:
    schedule: daily
    preferred_hour: 6
    job: youtube-sync-subscriptions
    agent: claude
    thinking_mode: fast
```

The runner constructs the agent prompt from the `job` field:
`"Read @docs/project/spec/jobs/{job}.md and execute the job instructions."`

The runner invokes `run_job()` which spawns a full interactive agent subprocess
via `subprocess.run()`. The agent has all tools enabled and MCP access when the
daemon is running. It loads its spec (its complete mandate), does its work,
writes a run report, and exits. The subprocess blocks until the agent completes
or the timeout is reached.

### Schedule Semantics

| Schedule | Minimum interval | Preferred timing                               |
| -------- | ---------------- | ---------------------------------------------- |
| hourly   | 1 hour           | —                                              |
| daily    | 20 hours         | `preferred_hour` (default 6)                   |
| weekly   | 6 days           | `preferred_weekday` (0=Mon) + `preferred_hour` |
| monthly  | 25 days          | `preferred_day` (1st) + `preferred_hour`       |

A job only runs when both conditions are met: minimum interval elapsed AND preferred
timing reached. Jobs that have never run execute immediately.

## State Persistence

File: `~/.teleclaude/cron_state.json`

```json
{
  "jobs": {
    "job_name": {
      "last_run": "2026-02-04T08:00:35.675556+00:00",
      "last_status": "success",
      "last_error": null
    }
  }
}
```

- `last_run`: ISO 8601 UTC timestamp
- `last_status`: `"success"` | `"failed"` | `"never"`
- `last_error`: Error message string or null
- State is saved after each job execution (success or failure)

## Failure Modes

- **Missing `teleclaude.yml`**: Engine logs a warning, no jobs run.
- **Job has no config entry**: Silently skipped (logged at debug level).
- **Job module fails to import**: Logged as error, other jobs still run.
- **Job raises exception during `run()`**: Caught, marked as failed in state, other jobs still run.
- **Invalid schedule value in config**: `Schedule(value)` raises `ValueError`, job skipped.
- **Agent job subprocess timeout**: `subprocess.run()` raises `TimeoutExpired`, marked as
  failed in state. Default timeout: 1800s (30 min), configurable per job via `timeout`.
- **Agent job fails mid-run**: Run report may be missing. The cron runner logs exit code.
  A missing report with a non-zero exit code indicates a crash.
- **Overlap (concurrent runner instances)**: Second instance detects pidfile, logs, exits
  cleanly. Stale pidfiles (process dead but file remains) are detected and overwritten.
- **Daemon unavailable during agent job**: Agent spawns without MCP tools. Filesystem-
  based jobs (prepare, gate) work normally. Jobs requiring teleclaude\_\_\* tools degrade
  gracefully — the tools are simply absent from the agent's tool set.

## Service Integration

- **Launchd label**: `ai.instrukt.teleclaude.cron`
- **Plist**: `templates/ai.instrukt.teleclaude.cron.plist`
- **Trigger**: Every 5 minutes (`StartInterval` = 300)
- **Installation**: `bin/init.sh` installs the cron plist alongside the daemon plist
- **Working directory**: Repository root
- **Logs**: `/var/log/instrukt-ai/teleclaude/cron.log`
- **Overlap prevention**: Pidfile at `~/.teleclaude/cron_runner.pid`

### CLI

```
cron_runner.py              Run all due jobs
cron_runner.py --force      Run all jobs regardless of schedule
cron_runner.py --job NAME   Run specific job only
cron_runner.py --dry-run    Check what would run without executing
cron_runner.py --list       List available jobs and their status
```

## Scripts vs Jobs

| Concern    | Scripts (`scripts/`)                           | Jobs (`jobs/`)                 |
| ---------- | ---------------------------------------------- | ------------------------------ |
| Invocation | Manual, one-off                                | Periodic via runner            |
| Scope      | Global (symlinked to `~/.teleclaude/scripts/`) | Repository-bound               |
| Use case   | Onboarding, ad-hoc operations                  | Recurring automation           |
| State      | None                                           | Tracked in `cron_state.json`   |
| Scheduling | None                                           | Configured in `teleclaude.yml` |

## Job Specs

Each job has a spec document in `docs/project/spec/jobs/` describing what it does,
how it works, its files, configuration, and known issues. The spec doc is the agent's
complete mandate — the agent reads it, executes it, and stays within its scope.

## Known Issues

1. **No tests.** No unit tests exist for the cron engine or job implementations.
