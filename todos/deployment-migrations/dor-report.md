# DOR Report: deployment-migrations

## Assessment Phase: Formal Gate

## Summary

Deployment-level migration framework for config files, state files, and directory
structures across version upgrades. Distinct from the existing database migration
system (`teleclaude/core/migrations/`). Uses a check/migrate contract with
idempotent numbered scripts, a runner, and CLI entry point.

## Gate Results

| Gate | Name                         | Status            | Notes                                                                                                                                                                                                                                                                      |
| ---- | ---------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Intent & success             | PASS              | Problem (breaking changes need auto-reconciliation) and outcome (idempotent migration scripts) are explicit. 8 testable success criteria in requirements.md.                                                                                                               |
| 2    | Scope & size                 | PASS              | Three tasks: manifest format, runner, CLI. Atomic, fits single AI session.                                                                                                                                                                                                 |
| 3    | Verification                 | PASS              | 6 unit tests specified covering discovery, ordering, skip, failure, atomic write, dry-run. Edge cases (crash mid-write, re-run idempotency) addressed in risks.                                                                                                            |
| 4    | Approach known               | PASS              | Technical path clear. check/migrate contract well-defined. Semver directory layout, importlib dynamic loading (pattern exists in `teleclaude/core/migrations/runner.py`), JSON state file with atomic writes. One decision resolved: dry-run is "all" not "per-migration". |
| 5    | Research complete            | PASS              | See analysis below.                                                                                                                                                                                                                                                        |
| 6    | Dependencies & preconditions | PASS (soft block) | Dependency `deployment-channels` exists but is `phase: pending`. This is a sequencing constraint, not a DOR blocker -- the work item is ready to build once its dependency delivers. No configs or access needed.                                                          |
| 7    | Integration safety           | PASS              | New module (`teleclaude/deployment/`), new directory (`migrations/`), new CLI subcommand. No existing code modified. Fully incremental, rollback = revert commit.                                                                                                          |
| 8    | Tooling impact               | PASS              | No scaffolding changes needed. CLI surface schema in `telec.py` will gain a `migrate` entry, which is additive.                                                                                                                                                            |

## Gate 5 Analysis: Research Gate

The draft flagged a blocker: "Migration patterns not yet researched and indexed."

**Assessment:** The proposed framework uses only:

- Python stdlib: `importlib.util`, `pathlib`, `json`, `tempfile`, `os.rename`
- Internal patterns: the existing `teleclaude/core/migrations/runner.py` already demonstrates `importlib.util.spec_from_file_location` for dynamic script loading, ordered numbered scripts (`NNN_name.py`), and state tracking -- the exact same patterns this work item needs
- No ORM, no SQL, no revision graph, no third-party migration library

The check/migrate contract is a simplification of the existing `up(db)` pattern, adapted from database to filesystem. No Alembic, Django, or Flyway code will be used. The "research" was about validating the pattern -- the codebase itself already validates it with 19 working migrations.

**Verdict:** Gate 5 auto-satisfied. No third-party dependencies. Internal prior art confirms the approach.

## Corrections Made

1. **`packaging.version.Version` claim removed.** The plan stated this was "already a dependency" -- it is not in `pyproject.toml` and not importable. Replaced with stdlib tuple comparison (`tuple(int(x) for x in ver.split('.'))`), which is sufficient for semver ordering and respects the "no new external dependencies" constraint.

2. **Module path clarified.** `teleclaude/deployment/migration_runner.py` targets a new package. This is correct but the builder should note this requires creating `teleclaude/deployment/__init__.py`.

## Plan-to-Requirement Fidelity

| Requirement                                                           | Plan Task      | Status                                  |
| --------------------------------------------------------------------- | -------------- | --------------------------------------- |
| Migration manifest format (`migrations/v{semver}/NNN_description.py`) | Task 1.1       | Covered                                 |
| check()/migrate() contract                                            | Task 1.1       | Covered                                 |
| Runner discovers migrations between versions                          | Task 1.2       | Covered                                 |
| Runner skips where check() returns True                               | Task 1.2       | Covered                                 |
| State tracking in `~/.teleclaude/migration_state.json`                | Task 1.2       | Covered                                 |
| Atomic state writes (temp + rename)                                   | Task 1.2       | Covered                                 |
| Failure halts and reports                                             | Task 1.2       | Covered                                 |
| `telec migrate --dry-run`                                             | Task 1.3       | Covered                                 |
| `telec migrate` runs all pending                                      | Task 1.3       | Covered                                 |
| No new external dependencies (constraint)                             | All tasks      | Verified: `packaging` reference removed |
| Idempotent (constraint)                                               | Task 1.1 + 2.1 | Covered by contract and test            |

No contradictions found. All requirements trace to plan tasks.

## Blockers

None. All 8 gates pass.

## Score

**9/10** -- All gates satisfied. Minor deduction: the plan could be more explicit about `teleclaude/deployment/__init__.py` creation and about how `telec migrate` integrates into the CLI surface schema in `telec.py` (the `CLI_SURFACE` dict). These are minor builder-level details, not DOR blockers.
