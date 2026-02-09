---
description: 'Scheduled job runner: architecture, job contract, and configuration surface.'
id: 'project/design/architecture/jobs-runner'
scope: 'project'
type: 'design'
---

# Jobs Runner — Design

## Purpose

A standalone scheduled process that discovers and executes periodic jobs.
Runs independently from the daemon — jobs can be long-running, don't require daemon
state, and can be force-run manually via CLI.

The runner is the engine for all periodic automation: subscription maintenance,
content digests, GitHub issue triage, and future scheduled tasks.

One-off operations (e.g., initial YouTube subscription fetch during onboarding)
live in `scripts/` or `teleclaude/entrypoints/` and are invoked directly — they
are not jobs.

## Architecture

```
launchd (hourly, minute 0)
  │
  ▼
scripts/cron_runner.py          CLI entry point
  │
  ▼
teleclaude/cron/runner.py       Engine: config → discover → schedule check → execute
  │  ├── _load_job_schedules()  Read schedule config from teleclaude.yml
  │  ├── discover_jobs()        Dynamic import of jobs/*.py (python-type jobs)
  │  ├── _run_agent_job()       Spawn headless agent session (agent-type jobs)
  │  ├── _is_due()              Evaluate schedule against last run timestamp
  │  └── run_due_jobs()         Main loop: config → is_due() → run/spawn → mark state
  │
  ▼
teleclaude.yml                  Schedule configuration (frequency, timing, job type)
  │
  ├── type: python (default)    → jobs/*.py modules (each exports a JOB instance)
  └── type: agent               → POST /sessions via daemon API (headless session)
  │
  ▼
~/.teleclaude/cron_state.json   Persistent state (last_run, status, errors)
```

### Job Types

**Python jobs** — Traditional modules in `jobs/*.py` with a `Job` subclass. The runner
imports the module, calls `job.run()`, and captures the `JobResult`. Use for jobs
with custom data processing logic (e.g., YouTube subscription tagging).

**Agent jobs** — Declared entirely in `teleclaude.yml` with `type: agent`. The runner
calls the daemon's `POST /sessions` REST API to spawn a headless agent session with a
message. The agent boots with full context (doc snippets, MCP tools, file system) and
runs to completion. Use for any job where the work IS "an AI doing things with tools."
No Python module needed.

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
- Updated state in `cron_state.json`
- Structured logs to `/var/log/instrukt-ai/teleclaude/cron.log`

## Invariants

- Jobs are schedule-ignorant. They define `name` and `run()` only. All scheduling
  configuration lives in `teleclaude.yml`.
- A job without a `teleclaude.yml` entry is never invoked (except with `--force`).
- A job that has never run executes immediately on first discovery.
- State is persisted after every job execution, success or failure.

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

#### Agent-type fields

| Field           | Type   | Default  | Description                                     |
| --------------- | ------ | -------- | ----------------------------------------------- |
| `type`          | string | (none)   | Set to `agent` for headless agent jobs          |
| `agent`         | string | `claude` | AI agent to use (`claude`, `gemini`, `codex`)   |
| `thinking_mode` | string | `fast`   | Model tier (`fast`, `med`, `slow`)              |
| `message`       | string | required | Task message sent to the agent at session start |

To add a Python job, create the module in `jobs/` AND register in `teleclaude.yml`.
To add an agent job, only a `teleclaude.yml` entry with `type: agent` is needed.

### Per-person: `~/.teleclaude/people/{name}/teleclaude.yml`

Person-scoped configuration for jobs that operate per-subscriber:

```yaml
subscriptions:
  youtube: youtube.csv # Relative to subscriptions/ dir
interests:
  tags:
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

### Normal execution (hourly launchd trigger)

1. `cron_runner.py` invokes `run_due_jobs()`.
2. Engine loads schedule config from `teleclaude.yml`.
3. Engine discovers job modules from `jobs/*.py`.
4. For each job with a config entry: load last run from state, evaluate `_is_due()`.
5. If due: call `job.run()`, persist result to state.
6. Jobs without config entries are silently skipped.

### Force run (CLI)

`cron_runner.py --force` bypasses all schedule checks. Every discovered job runs
regardless of config or last run time.

## Job Contract

### Python jobs

1. Create `jobs/<name>.py`
2. Subclass `Job` from `jobs.base`
3. Set `name` (unique string)
4. Implement `run() -> JobResult`
5. Export a module-level `JOB` instance
6. Register the job in `teleclaude.yml` under `jobs:` with schedule config

```python
from jobs.base import Job, JobResult

class MyJob(Job):
    name = "my_job"

    def run(self) -> JobResult:
        # do work
        return JobResult(success=True, message="Done", items_processed=5)

JOB = MyJob()
```

```yaml
# teleclaude.yml
jobs:
  my_job:
    schedule: daily
    preferred_hour: 8
```

### Agent jobs

For jobs where the work IS "an AI doing things with tools," no Python module
is needed. Declare the job in `teleclaude.yml` with `type: agent`:

```yaml
jobs:
  memory_review:
    schedule: weekly
    preferred_weekday: 0
    preferred_hour: 8
    type: agent
    agent: claude
    thinking_mode: fast
    message: >-
      Your task instructions here. The agent boots with full context
      (doc snippets, MCP tools, file system) and runs to completion.
```

The runner spawns a headless agent session via `POST /sessions` on the daemon's
unix socket. The agent receives the message, does its work, and exits.
Fire-and-forget: the cron runner marks success when the session spawns, not
when the agent completes.

Create a spec doc at `docs/project/spec/jobs/<name>.md` for agent jobs —
the agent can read it via `@docs/...` references in the message.

### Schedule Semantics

| Schedule | Minimum interval | Preferred timing                               |
| -------- | ---------------- | ---------------------------------------------- |
| hourly   | 1 hour           | —                                              |
| daily    | 20 hours         | `preferred_hour` (default 6)                   |
| weekly   | 6 days           | `preferred_weekday` (0=Mon) + `preferred_hour` |
| monthly  | 25 days          | `preferred_day` (1st) + `preferred_hour`       |

A job only runs when both conditions are met: minimum interval elapsed AND preferred
timing reached. Jobs that have never run execute immediately.

### JobResult

```python
@dataclass
class JobResult:
    success: bool
    message: str
    items_processed: int = 0
    errors: list[str] | None = None
```

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

## Service Integration

- **Launchd label**: `ai.instrukt.teleclaude.cron`
- **Plist**: `launchd/ai.instrukt.teleclaude.cron.plist`
- **Trigger**: Every hour at minute 0
- **Working directory**: Repository root
- **Logs**: `/var/log/instrukt-ai/teleclaude/cron.log`

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
how it works, its files, configuration, and known issues.

## Known Issues

1. **Launchd plist not installed by automation.** `bin/init.sh` and `Makefile` have no
   cron references. The plist must be installed manually.
2. **No tests.** No unit tests exist for the cron engine or job implementations.
