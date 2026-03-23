# Test Spec Review Findings: session-memory-extraction

## Summary

The test specifications provide a solid foundation for verifying the behavioral contract of the memory extraction job. However, the review is blocked by empty requirements, and several policy and rigor findings must be addressed before approval.

## Findings

### Critical

- **Empty Requirements**: `requirements.md` is an empty template. Test specifications must be evaluated against explicit requirements. This review proceeded using `input.md` as the source of truth, but the task cannot move to the next phase until requirements are properly drafted.

### Important

- **Mirror Convention Violation**: `tests/unit/test_session_memory_extraction.py` is not located at the expected path based on its source file (`jobs/session_memory_extraction.py`). It should be moved to `tests/unit/jobs/test_session_memory_extraction.py` as per the **Test Structure — Policy**.
- **Excessive Mocking**: `test_extract_actionable_items_publishes_each_item_to_the_project_channel` uses 7 mock patches, exceeding the project's limit of 5. Consider refactoring the test or the job's dependencies (e.g., using a mock publisher or channel helper instead of patching multiple modules).
- **Missing Boundary Coverage**: `test_read_transcript_delta` does not cover boundary conditions:
  - Case where `get_mirror` returns `None`.
  - Case where no messages are found since `last_memory_extraction_at`.
- **Missing Extraction Optimization Check**: `test_process_session` should verify that if `_read_transcript_delta` returns an empty string, the LLM extraction methods are skipped entirely to avoid unnecessary cost.
- **Identity Key Resolution Handling**: The test for `_process_session` assumes `_resolve_identity_key` always returns a key. It should also verify the behavior when it returns `None` (likely skipping personal memory extraction).

### Suggestions

- **Test-Only Class names**: Consider using standard `TestJobName` naming for the test class instead of `TestJobNameSpecs` (though this is minor).
- **Parametrization**: Some of the extraction tests could benefit from `pytest.mark.parametrize` to cover different LLM output scenarios (e.g., multiple items, single item, zero items).

## Verdict

`needs_work`
