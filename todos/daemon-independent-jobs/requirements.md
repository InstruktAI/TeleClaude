# Requirements: Daemon-Independent Job Execution

## Goal

Make agent-type cron jobs run as daemon-independent subprocess invocations. Replace
the current `POST /sessions` daemon API call with a direct subprocess spawn that gives
the agent full tool and MCP access. Add role-aware invocation so jobs can run with
appropriate permissions, falling back silently to admin when the daemon is unavailable.
Automate cron plist installation and increase trigger granularity to 5 minutes.

## Problem Statement

1. **Agent jobs require the daemon.** `_run_agent_job()` posts to the daemon's unix
   socket to spawn a headless session. If the daemon is down, agent jobs fail entirely.
   The cron runner's resilience advantage over an internal scheduler is negated.

2. **No role awareness.** Agent jobs have no concept of caller role. The invocation
   mechanism doesn't pass identity context. Future jobs that use `get_context` need
   role-based visibility filtering, which requires the role to propagate.

3. **Plist not installed by automation.** `bin/init.sh` installs the daemon plist but
   not the cron plist. The cron runner has never fired via launchd on any installation.

4. **Hourly granularity is too coarse.** Jobs with `preferred_hour` or `when.at` times
   can miss their window entirely if the plist fires at the wrong minute.

5. **`--list` hides agent jobs.** The CLI list command only shows Python script jobs
   discovered from `jobs/*.py`. Agent jobs from teleclaude.yml are invisible.

6. **No overlap prevention.** Launchd spawns a new runner every trigger even if the
   previous is still running.

## Scope

### In scope

1. **New invocation function** in `agent_cli.py` — `run_job()` that spawns a full
   interactive agent subprocess with tools and MCP enabled. Not a modification of
   `run_once` (which is deliberately lobotomized for JSON-only calls).

2. **`_run_agent_job()` rewrite** — Replace daemon API call with `subprocess.run()`
   using the new invocation function. Agent runs to completion as a child process.

3. **Role-aware invocation** — `run_job()` accepts a `role` parameter. When the daemon
   is available, role can be resolved from config. When the daemon is down, silently
   default to admin. The role is passed to the agent environment (marker file or env var)
   for MCP tool filtering.

4. **Cron plist installation** — Add `install_launchd_cron()` to `bin/init.sh` alongside
   existing `install_launchd_service()`.

5. **5-minute granularity** — Update plist `StartInterval` from 3600 to 300.

6. **`--list` fix** — Include agent jobs from teleclaude.yml in list output.

7. **Overlap prevention** — Pidfile or timestamp-based guard so concurrent runners
   detect and skip if another instance is active.

8. **Documentation updates** — Update jobs-runner design doc and agent-job-hygiene
   procedure to reflect the new execution model.

### Out of scope

- Modifying `run_once()` — it stays lobotomized for structured JSON output.
- Full person-identity-auth integration — role defaults to admin for system jobs.
- Cross-project visibility filtering — future jobs that need `get_context` with
  visibility will benefit from the role plumbing, but that's a downstream concern.
- New job definitions — this todo changes the execution mechanism, not the jobs.
- `telec init` changes — `telec init` is project-level; cron is system-level (`bin/init.sh`).

## Success Criteria

- [ ] Agent jobs spawn and complete without the daemon running.
- [ ] Agent jobs have full tool access (bash, read, write, glob, grep, etc.).
- [ ] Agent jobs have MCP access when the teleclaude MCP server is reachable.
- [ ] MCP unavailability does not prevent job execution (graceful degradation).
- [ ] Role parameter is accepted and passed to agent environment; defaults to admin.
- [ ] `make init` installs both daemon and cron launchd plists.
- [ ] Cron runner fires every 5 minutes via launchd.
- [ ] `--list` shows both Python and agent jobs with schedule and status.
- [ ] Concurrent runner instances are prevented (second instance exits cleanly).
- [ ] Existing prepare jobs (next-prepare-draft, next-prepare-gate) work end-to-end
      via the new subprocess path.
- [ ] Jobs-runner design doc and agent-job-hygiene procedure updated.

## Constraints

- Must not break `run_once()` — it has a separate purpose (YouTube tagger, etc.).
- Must not require daemon for any cron runner operation.
- Agent subprocess must self-terminate when done (no orphan sessions).
- Keep the fire-and-wait model simple: `subprocess.run()` with a timeout.

## Risks

- **Long-running agent jobs block the runner.** Unlike fire-and-forget daemon sessions,
  subprocess.run blocks. Mitigate with per-job timeout and sequential execution
  (one job at a time, not parallel).
- **MCP wrapper daemon dependency.** The MCP wrapper connects to the daemon socket.
  If daemon is down, teleclaude MCP tools are unavailable. Current prepare jobs don't
  need MCP (they work on filesystem), so this is acceptable degradation.
- **Claude Code `@` reference resolution.** `@` references in spec docs resolve via
  filesystem, not MCP. This works daemon-independently. Verified.

## Dependencies

- None hard. Current prepare jobs work immediately without daemon, MCP, or role system.
- Soft: `cross-project-context` (visibility filtering) and `person-identity-auth-3`
  (human role gating) enhance the role story for future jobs.
