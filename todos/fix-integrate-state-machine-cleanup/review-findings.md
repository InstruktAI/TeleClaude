# Review Findings: fix-integrate-state-machine-cleanup

Ad-hoc review (via from-main).

## Code Review

- `teleclaude/cli/api_client.py`: Added `run_session` method to support `/sessions/run`.
- `teleclaude/cli/telec/handlers/bugs.py`: Updated bug reporting to use `run_session`.
- `teleclaude/cli/telec/surface.py`: Made `--project` optional for `start` and `run` commands.
- `teleclaude/cli/tool_commands/sessions.py`: Implemented default-to-cwd logic.
- `teleclaude/core/integration/step_functions.py`:
  - Added stale artifact sweep on IDLE entry.
  - Made repo root pull non-blocking in `PUSH_SUCCEEDED`.
  - Added logging for previously swallowed exceptions.

## Paradigm Fit

- Implementation follows established patterns for CLI/API and state machine logic.

## Principles

- **Silent Degradation**: Fixed by adding `logger.debug(..., exc_info=True)` to previously silent exception handlers.
- **Robustness**: Integration state machine is now more robust against repo root sync failures.

## Security

- No security issues identified.

## Tests

- Added unit tests for `_sweep_stale_artifacts` in `tests/unit/core/integration/test_step_functions.py`.
- Verified existing tests for bookkeeping and CLI sessions pass.

## Errors

- Silent failures in file reading and event emission are now logged at DEBUG level.

## Documentation

- CLI help text and surface notes updated to reflect that `--project` is optional.

## Resolved During Review

- Added unit tests for `_sweep_stale_artifacts` to ensure its logic (idempotency, filtering) is verified.

## Verdict: APPROVE
