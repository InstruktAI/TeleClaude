# Review Findings — agent-output-monitor

## Critical

- None.

## Important

- Failed verification commands are currently treated as successful evidence. `_has_evidence()` and `_has_status_evidence()` only match command substrings and ignore `ToolCallRecord.had_error`, so a failed `make restart` suppresses the required restart action and can produce a false all-clear (`teleclaude/hooks/checkpoint.py:130`, `teleclaude/hooks/checkpoint.py:143`, `teleclaude/hooks/checkpoint.py:366`).
- JSONL checkpoint extraction is still not I/O-bounded. `_iter_jsonl_entries_tail()` reads the entire file into a deque before returning the last entries, which violates the bounded tail-read requirement for large transcripts (`teleclaude/utils/transcript.py:657`).
- Capture-only (docs-only) checkpoint messages omit the required baseline log-check instruction. The docs-only branch returns immediately without `instrukt-ai-logs teleclaude --since 2m` (`teleclaude/hooks/checkpoint.py:419`).

## Suggestions

- Add regression tests that failed `make restart` and failed `make status` do not count as suppression evidence (`tests/unit/test_checkpoint_builder.py`).
- Add an explicit assertion for docs-only capture flow requiring the baseline log-check instruction (`tests/unit/test_checkpoint_builder.py`).
- Add a transcript extraction test that verifies bounded read behavior by byte window rather than by tail entry count (`tests/unit/test_transcript_extraction.py`).

## Verdict

REQUEST CHANGES
