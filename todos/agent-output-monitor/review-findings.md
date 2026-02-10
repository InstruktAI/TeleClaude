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

REQUEST CHANGES
