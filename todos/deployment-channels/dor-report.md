# DOR Report: deployment-channels

## Assessment Phase: Formal Gate

## Summary

Deployment channel config and version watcher job. Clear, well-scoped work item with
concrete deliverables. Uses existing jobs infrastructure. Several inaccuracies in
file paths, scheduling syntax, and demo commands were tightened during this gate.

## Gate Results

| #   | Gate                         | Score | Status | Notes                                                        |
| --- | ---------------------------- | ----- | ------ | ------------------------------------------------------------ |
| 1   | Intent & success             | 9     | PASS   | Clear problem, testable success criteria                     |
| 2   | Scope & size                 | 9     | PASS   | Atomic, fits single session (config schema + 1 job + CLI)    |
| 3   | Verification                 | 8     | PASS   | Unit tests defined, edge cases (network failure) noted       |
| 4   | Approach known               | 7     | PASS   | Tightened below; was referencing wrong syntax/paths          |
| 5   | Research complete            | 8     | PASS   | GitHub API + git ls-remote approaches sound                  |
| 6   | Dependencies & preconditions | 8     | PASS   | `deployment-versioning` is ready (DOR passed, build pending) |
| 7   | Integration safety           | 9     | PASS   | Additive only; new config key, new job, CLI update           |
| 8   | Tooling impact               | 9     | PASS   | No scaffolding changes needed                                |

## Plan-to-Requirement Fidelity

All plan tasks trace to requirements:

| Requirement                                       | Plan Task |
| ------------------------------------------------- | --------- |
| `deployment.channel` configurable with validation | 1.1       |
| Default channel is `alpha`                        | 1.1       |
| Version watcher runs on cron schedule             | 1.2, 1.3  |
| Alpha: git ls-remote detection                    | 1.2       |
| Beta: GitHub release detection                    | 1.2       |
| Stable: pinned minor patch detection              | 1.2       |
| Signal file written/removed                       | 1.2       |
| `telec version` shows configured channel          | 1.4       |

No contradictions. No orphan plan tasks.

## Actions Taken (Formal Gate)

### Inaccuracies tightened

1. **Config file naming**: Input/requirements loosely reference "config.yaml". The actual
   config files are `teleclaude.yml` (project and global level). The schema is in
   `teleclaude/config/schema.py`. Requirements already correctly reference teleclaude.yml.

2. **Schedule syntax**: Plan Task 1.3 said `schedule: "*/5 * * * *"` (cron syntax).
   The actual scheduling system uses the `when` contract: `when: { every: "5m" }`.
   The legacy `schedule` field only supports `hourly|daily|weekly|monthly`.

3. **Job registration**: Plan Task 1.3 mentioned registering in `jobs/__init__.py`.
   This is unnecessary -- the cron runner dynamically discovers `jobs/*.py` modules via
   `discover_jobs()`. No manual registration is needed.

4. **Job terminology**: Input calls this a "script job". In the codebase, these are
   "python jobs" (modules in `jobs/*.py` that export a `JOB` instance). The `script`
   field in `JobScheduleConfig` is a separate concept (a path to a script for direct
   execution). The version watcher follows the python job pattern: subclass `Job`,
   export `JOB` instance, register schedule in `teleclaude.yml`.

5. **Demo commands**: `from teleclaude.config.schema import validate_config` does not
   exist in schema.py. The function is in `teleclaude/config/loader.py`. Demo should
   reference the correct import path or test schema validation directly.

6. **Config schema location**: Plan Task 1.1 says `teleclaude/config/schema.py` which
   is correct, but should clarify: add a `DeploymentConfig` model and reference it from
   `ProjectConfig` (since deployment config is project-level).

### Dependency verification

- `deployment-versioning` (prerequisite): `phase: ready`, `build: pending`, DOR score 9.
  This todo delivers `__version__` and `telec version` which this todo depends on.
  Task 1.4 (update telec version) and Task 1.2 (beta: compare with `__version__`)
  require `deployment-versioning` to be built first. The roadmap correctly enforces
  `after: [deployment-versioning]`.

### Codebase verification

- `teleclaude/config/schema.py`: Confirmed Pydantic models, `ProjectConfig` has `jobs` dict.
  Adding a `deployment` key is straightforward.
- `jobs/base.py`: Confirmed `Job` ABC with `name` and `run() -> JobResult`.
- `jobs/__init__.py`: Only exports `Job`. No manual registration needed.
- `teleclaude/cron/runner.py`: Confirmed `discover_jobs()` auto-imports `jobs/*.py`,
  `_is_due()` supports `when.every` durations, `run_due_jobs()` handles both python
  and agent jobs.
- `teleclaude.yml`: Confirmed existing job entries use legacy `schedule` field.
  The `when` contract is supported by the schema and runner.
- `pyproject.toml`: Currently at `version = "0.1.0"`.

## Blockers

None. All issues were tightened in-place. Dependency is sequenced correctly.

## Verdict

**Score: 8/10 -- PASS**

Artifacts are ready for build. The inaccuracies identified are minor and well-documented
above. The builder should reference this DOR report for corrected file paths and
scheduling syntax.
