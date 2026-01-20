---
id: standard/definition-of-done
type: standard
scope: project
description: Quality gates and verification steps required for completing code changes.
---

# Definition of Done (DoD)

## Requirements
Before reporting a task as complete, an agent MUST:
1. **Implement Logic**: Complete the feature or fix according to requirements.
2. **Automated Tests**:
   - Add unit tests in `tests/unit/`.
   - Add integration tests in `tests/integration/` if boundaries are touched.
   - Run `make test` and ensure all tests pass.
3. **Static Analysis**:
   - Run `make lint` (ruff, mypy, pylint).
   - Fix all reported errors.
4. **Runtime Verification**:
   - `make restart` to deploy changes to the local daemon.
   - `make status` to verify the daemon is healthy.
5. **No Clutter**: Ensure no temporary files or duplicate databases remain.

## Rule of Thumb
"Done" means the code is tested, linted, running, and verified. Manual inspection is never a substitute for automated tests.