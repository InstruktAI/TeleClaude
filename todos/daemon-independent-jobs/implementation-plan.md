# Implementation Plan: Daemon-Independent Job Execution

## Overview

Replace the daemon-dependent agent job spawning with direct subprocess invocation.
The cron runner becomes fully self-contained: it resolves the agent binary, builds
CLI flags (with tools and MCP enabled), spawns a subprocess, and waits for completion.
Role defaults to admin when the daemon is unavailable.

Documentation updates come first (design doc + procedure), then code changes, then
infrastructure (plist installation).

---

## Phase 1: Documentation (docs-first)

### Task 1.1: Update jobs-runner design doc

**File(s):** `docs/project/design/architecture/jobs-runner.md`

- [x] Rewrite the architecture diagram to show subprocess path instead of daemon API
- [x] Add `run_job()` as third execution mode alongside `run_once()` and script `run()`
- [x] Document the role resolution chain: daemon available → resolve from config;
      daemon down → silent admin fallback
- [x] Update execution mode table: `run_once` (lobotomized JSON), `run_job` (interactive
      subprocess with tools+MCP), script `run()` (direct Python)
- [x] Update service integration section: 5-minute granularity, plist auto-installation
- [x] Remove Known Issue #1 (plist not installed by automation)
- [x] Add overlap prevention to failure modes
- [x] Update the job contract section for agent jobs to reflect subprocess model

### Task 1.2: Update agent-job-hygiene procedure

**File(s):** `docs/global/general/procedure/agent-job-hygiene.md`

- [x] Update precondition: "spawned by the cron runner as a subprocess" (not headless session)
- [x] Note that tools and filesystem access are available
- [x] Note that MCP tools (teleclaude\_\_\*) are available when daemon is running,
      gracefully absent when daemon is down

---

## Phase 2: Core Code Changes

### Task 2.1: New `run_job()` function in agent_cli.py

**File(s):** `teleclaude/helpers/agent_cli.py`

- [ ] Add `_JOB_SPEC` dict alongside existing `_ONESHOT_SPEC` — same agent binaries
      but WITHOUT `--tools ""` and WITHOUT `enabledMcpjsonServers: []`
- [ ] Keep `--dangerously-skip-permissions` and `--no-chrome`
- [ ] Keep `--no-session-persistence` (jobs are stateless between runs)
- [ ] Accept parameters: `agent`, `thinking_mode`, `prompt`, `role` (default "admin"),
      `timeout_s` (default None)
- [ ] Set `TELECLAUDE_JOB_ROLE` env var on the subprocess so downstream MCP wrapper
      can read it for tool filtering
- [ ] Use `subprocess.run()` with `timeout=timeout_s`
- [ ] Return exit code (success/failure), not parsed JSON

### Task 2.2: Rewrite `_run_agent_job()` to use subprocess

**File(s):** `teleclaude/cron/runner.py`

- [ ] Replace `_UnixSocketConnection` + `POST /sessions` with call to `run_job()`
- [ ] Remove `_UnixSocketConnection` class (dead code after rewrite)
- [ ] Remove `_DAEMON_SOCKET` constant
- [ ] Role resolution: attempt daemon socket health check; if unreachable, default "admin"
- [ ] Pass `timeout_s` from teleclaude.yml config (new optional field) or default (30 min)
- [ ] Map subprocess exit code to success/failure for state persistence

### Task 2.3: Fix `--list` to show agent jobs

**File(s):** `scripts/cron_runner.py`

- [ ] After `discover_jobs()`, also iterate `_load_job_schedules()` for agent-type entries
- [ ] Include agent jobs in the list output with schedule, last run, and status
- [ ] Mark type column: "script" vs "agent"

### Task 2.4: Add overlap prevention

**File(s):** `teleclaude/cron/runner.py`

- [ ] At start of `run_due_jobs()`: check for pidfile at `~/.teleclaude/cron_runner.pid`
- [ ] If pidfile exists and process is alive: log and exit cleanly
- [ ] Write pidfile on entry, remove on exit (use atexit for cleanup)
- [ ] Handle stale pidfiles (process dead but file remains)

---

## Phase 3: Infrastructure

### Task 3.1: Add cron plist installation to bin/init.sh

**File(s):** `bin/init.sh`

- [ ] Add `install_launchd_cron()` function after `install_launchd_service()`
- [ ] Use existing `launchd/ai.instrukt.teleclaude.cron.plist` template
- [ ] Same pattern as daemon plist: bootout old, bootstrap new
- [ ] Call from `main()` after `install_service`

### Task 3.2: Update plist to 5-minute granularity

**File(s):** `launchd/ai.instrukt.teleclaude.cron.plist`

- [ ] Replace `StartCalendarInterval` block (fires once per hour at minute 0)
      with `StartInterval` key set to 300 (fires every 5 minutes)
- [ ] Verify `StandardOutPath` points to `/var/log/instrukt-ai/teleclaude/cron.log`

### Task 3.3: Add optional `timeout` field to job config schema

**File(s):** `teleclaude/config/schema.py`

- [ ] Add `timeout: Optional[int] = None` to `JobScheduleConfig` (seconds)
- [ ] Default behavior when absent: 30 minutes for agent jobs

---

## Phase 4: Validation

### Task 4.1: Manual end-to-end test

- [ ] Stop daemon (`make stop`)
- [ ] Run: `.venv/bin/python scripts/cron_runner.py --force --job next_prepare_draft`
- [ ] Verify agent spawns, reads spec, processes todos, writes report, exits
- [ ] Verify `cron_state.json` updated with success
- [ ] Start daemon (`make start`)
- [ ] Run again — verify same behavior with daemon running

### Task 4.2: Unit tests

- [ ] Test `run_job()` invocation builds correct CLI flags (no `--tools ""`)
- [ ] Test `_run_agent_job()` calls `run_job()` instead of daemon API
- [ ] Test overlap prevention (pidfile logic)
- [ ] Test `--list` output includes agent jobs
- [ ] Test role fallback (daemon unreachable → admin)

### Task 4.3: Quality checks

- [ ] Run `make lint`
- [ ] Run `make test`
- [ ] Verify `telec sync` passes

---

## Phase 5: Review Readiness

- [ ] Confirm requirements reflected in code changes
- [ ] Confirm all implementation tasks marked `[x]`
- [ ] Jobs-runner design doc updated
- [ ] Agent-job-hygiene procedure updated
- [ ] Document any deferrals explicitly
