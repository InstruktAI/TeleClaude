# Demo: fix-integrator-session-start-no-focus

This demo uses the focused TUI session-start regression tests as executable proof for
the auto-focus behavior:

- daemon-started sessions do not steal focus
- TUI-created sessions do auto-focus
- TUI-created run sessions with `session_metadata.job` still auto-focus

```bash
pytest -q tests/unit/cli/tui/test_app_ws.py -k "daemon_spawned_session_does_not_auto_focus or user_initiated_session_auto_focuses or user_run_session_with_job_auto_focuses"
```

Expected result: `3 passed`
