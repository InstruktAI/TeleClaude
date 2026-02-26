# Deferrals: adapter-output-qos-scheduler

## Deferred tasks

### Task 5.2: Integration/load checks

**Reason:** Requires a running daemon with active sessions and Telegram credentials.
Not feasible in the worktree build environment.

**Path:** Run post-merge on the live deployment:

```bash
# Simulate N=20 sessions via test harness or organic load.
# Monitor: instrukt-ai-logs teleclaude --since 15m --grep "Output cadence summary"
# Verify: queue_depth stabilizes, no runaway flood-control retries.
```

### Task 5.3: Runtime validation

**Reason:** Requires `make restart` and log observation on a live instance.
Not available in worktree.

**Path:** Post-merge validation:

```bash
make restart
make status
instrukt-ai-logs teleclaude --since 5m --grep "OutputQoSScheduler started|Output cadence summary"
```

Expected log entries:

- `OutputQoSScheduler started: adapter=telegram mode=strict`
- `OutputQoSScheduler started: adapter=discord mode=coalesce_only`
- `[QoS telegram] Output cadence summary: mode=strict tick_s=3.80 ...` (every 30s)
