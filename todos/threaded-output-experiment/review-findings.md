REVIEW COMPLETE: threaded-output-experiment

Critical:

- Lint gate is failing on the current outstanding change set. `ruff check` reports 12 violations (import sort and unused imports), including `tests/integration/test_ai_to_ai_regression.py:8`, `tests/integration/test_run_agent_command_e2e.py:7`, `tests/unit/test_ansi_stripping.py:213`, and `tests/unit/test_polling_coordinator.py:9`.

Important:

- `todos/threaded-output-experiment/input.md:1` conflicts with implemented/approved config direction (`ui.experiments.incremental_threaded_output` in input vs `experiments.yml` overlay in requirements and code). Keep only one source-of-truth shape to avoid implementation drift.
- The earlier plan coverage gap remains for this todo: `todos/threaded-output-experiment/implementation-plan.md:114` marks config overlay tests complete, but no test currently exercises module-level optional `experiments.yml` loading behavior (present/absent file) in `teleclaude/config.py`.

Suggestions:

- Add a focused config-loading test that monkeypatches `TELECLAUDE_CONFIG_PATH` + temp `experiments.yml` and reloads `teleclaude.config` to verify merge behavior.
- Run `ruff check --fix` on the new test files, then re-run the targeted integration tests (`tests/integration/test_ai_to_ai_regression.py`, `tests/integration/test_run_agent_command_e2e.py`) to preserve current functional pass status.

Verdict: REQUEST CHANGES
