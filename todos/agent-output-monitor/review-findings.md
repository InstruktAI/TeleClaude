# Review Findings — agent-output-monitor

## Critical

- None.

## Important

- Error-state detection can suppress unresolved failures when repeated error records are value-identical. In `_check_error_state`, `timeline.tool_calls.index(error_record)` uses value equality for dataclasses, so duplicate records resolve to the first index and the later unresolved error can be treated as already addressed (`teleclaude/hooks/checkpoint.py:167`). This currently reproduces as a silent false negative for two identical failed `pytest` calls in one turn.
- The `tests only` category is applied even when source files changed, which violates the requirement that it only applies for `tests/**/*.py` with no source changes. Current categorization includes both `daemon code` and `tests only` for mixed diffs, causing duplicated/contradictory test actions (`teleclaude/constants.py:172`, `teleclaude/hooks/checkpoint.py:351`).
- Transcript scanning is not bounded for JSONL checkpoints despite the explicit requirement to tail-read recent data. `extract_tool_calls_current_turn()` loads all entries through `_get_entries_for_agent()`, and JSONL iteration reads the entire file (`teleclaude/utils/transcript.py:636`, `teleclaude/utils/transcript.py:1062`, `teleclaude/utils/transcript.py:1484`).
- `docs/project/index.yaml` was rewritten to a worktree-specific absolute root (`~/Workspace/InstruktAI/TeleClaude/trees/agent-output-monitor`), which is environment-specific and will misconfigure doc indexing for other clones/machines (`docs/project/index.yaml:1`).

## Suggestions

- Add a regression test for duplicate unresolved error records (same command and same result snippet) to lock down the `_check_error_state` fix path (`tests/unit/test_checkpoint_builder.py`).
- Add an assertion that mixed source+test diffs do not emit the `tests only` category or duplicate test action lines (`tests/unit/test_checkpoint_builder.py`).

## Verdict

REQUEST CHANGES

## Fixes Applied

- Issue: Error-state detection could miss unresolved duplicate error records due to value-based index lookup.
  Fix: `_check_error_state` now iterates with positional indexes (`enumerate`) so subsequent slicing is bound to the actual record instance order; added duplicate-failure regression coverage.
  Commit: `ec95b569`
- Issue: `tests only` category incorrectly applied to mixed source+test diffs.
  Fix: `_categorize_files` now emits `tests only` only when all changed files match that category; added mixed-diff regression checks for category and action deduplication.
  Commit: `aea91203`
- Issue: Current-turn tool-call extraction scanned full JSONL transcripts instead of tail-bounded recent data.
  Fix: Added tail-bounded JSONL iterators and wired `extract_tool_calls_current_turn()` to load only recent entries for Claude/Codex; added regression test for `tail_entries`.
  Commit: `e0ab8715`
- Issue: `docs/project/index.yaml` used a worktree-specific absolute root.
  Fix: Normalized `project_root` and `snippets_root` to the canonical repo root path instead of the worktree path.
  Commit: `2733f5f7`
