# Review Findings — agent-output-monitor

## Critical

- None.

## Important

- Mixed `tests + docs` diffs are misclassified as all-clear. `_categorize_files()` requires every changed file to match `tests/**/*.py`, so adding any markdown file drops the `tests only` category and can lead to `All expected validations were observed` with no test instruction (`teleclaude/hooks/checkpoint.py:90`, `teleclaude/hooks/checkpoint.py:403`, `teleclaude/hooks/checkpoint.py:432`).
- Hook-runtime-only changes skip the required log check. `run_heuristics()` gates `instrukt-ai-logs` behind `has_code_changes`, but that flag excludes `"hook runtime"`, so hook code changes can miss observability guidance (`teleclaude/hooks/checkpoint.py:385`).
- Duplicate restart actions are emitted when both daemon and config files change. The category loop appends identical `Run \`make restart\` then \`make status\`` actions without deduplication (`teleclaude/hooks/checkpoint.py:366`, `teleclaude/hooks/checkpoint.py:376`).
- Working-slug file extraction mishandles plan rows annotated with `(NEW)`. `_extract_plan_file_paths()` leaves trailing backtick/annotation text in parsed paths, which can create false drift observations for new-file tasks (`teleclaude/hooks/checkpoint.py:340`).

## Suggestions

- Add regression coverage for `tests + docs` diffs so they still produce a tests-required action (`tests/unit/test_checkpoint_builder.py`).
- Add a hook-runtime-only test asserting `instrukt-ai-logs teleclaude --since 2m` is required when not observed (`tests/unit/test_checkpoint_builder.py`).
- Deduplicate required actions and assert single restart/status instruction for `daemon + config` diffs (`tests/unit/test_checkpoint_builder.py`).
- Parse only fenced file paths from the plan table and strip annotations like `(NEW)` before overlap checks (`teleclaude/hooks/checkpoint.py`).

## Verdict

APPROVE

## Fixes Applied

- Issue: Mixed `tests + docs` diffs were not treated as tests-required, allowing false all-clear outcomes.
  Fix: `_categorize_files()` now evaluates tests-only against non-doc/non-todo files so `tests + docs` still maps to tests-required behavior; added regression test `test_tests_plus_docs_still_requires_tests_action`.
  Commit: `3dcfeee5`
- Issue: Hook-runtime-only changes skipped required log-check guidance.
  Fix: `run_heuristics()` now treats hook runtime as code change for log-check requirements (while still excluding tests-only); added regression test `test_hook_runtime_only_requires_log_check_when_missing`.
  Commit: `30ee8b7b`
- Issue: Duplicate restart actions were emitted when daemon and config changed together.
  Fix: Added ordered deduplication for required actions in `run_heuristics()` and covered it with `test_daemon_and_config_emit_single_restart_action`.
  Commit: `1502e687`
- Issue: Working-slug plan file parsing included trailing annotations like `(NEW)`.
  Fix: `_extract_plan_file_paths()` now extracts the fenced file path token from the plan table cell, ignoring trailing annotations; added regression test `test_slug_overlap_ignores_new_annotation_in_plan`.
  Commit: `b0232920`

## Orchestrator Round-Limit Closure

- Decision: APPROVE at review round limit.
- Basis:
  - No unresolved Critical findings.
  - All Important findings are addressed with dedicated fix commits (`3dcfeee5`, `30ee8b7b`, `1502e687`, `b0232920`) and recorded above.
  - Latest worker validation reported passing lint and checkpoint-focused tests.
- Residual risk handling: no blocking findings remain; continue to lifecycle completion.
