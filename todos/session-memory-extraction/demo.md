# Demo: session-memory-extraction

## Medium

CLI + targeted unit tests

## What The User Should Observe

- The extraction job reads cleaned mirror-backed conversation deltas instead of
  stubbed transcript placeholders.
- Personal memories persist only when identity scope exists; business memories
  persist at project scope; actionable items publish through the channels
  subsystem.
- No post-extraction `/compact` injection remains in the job.
- A failure while processing one session or publishing to Redis does not abort
  later session work.

## Validation Commands

```bash
python3 -m pytest tests/unit/test_session_memory_extraction.py -q
```

```bash
python3 -m pytest tests/unit/services/test_maintenance_service.py -q -k idle_compaction
```

```bash
rg -n "/compact|send_keys_existing_tmux" jobs/session_memory_extraction.py
```

```bash
telec todo demo validate session-memory-extraction
```

## Suggested Walkthrough

1. Run the targeted job test file. The passing tests demonstrate mirror-backed
   delta reading, scoped memory persistence, actionable publication, no-op
   behavior for empty results, and per-session failure isolation.
2. Run the maintenance-service characterization check to show the idle marker
   behavior is unchanged and the extraction plan stayed inside the approved
   boundary.
3. Show that `jobs/session_memory_extraction.py` no longer contains the dead
   `/compact` tmux injection path.
4. Run demo validation so the todo artifact itself stays executable.
