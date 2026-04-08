# Test Spec Review: codex-global-compaction-delivery-correction

**Review Date:** 2026-04-06
**Reviewer:** Claude Code (Haiku 4.5)
**Scope:** Test specifications for R1–R4 requirements
**Verdict:** APPROVE

---

## Overview

Test specifications for `codex-global-compaction-delivery-correction` are comprehensive, well-structured, and address all critical requirements. The specs demonstrate strong understanding of the architectural requirements and use appropriate test patterns (xfail, mocking, parametrization, exact assertions).

**Summary:**

- 2 test files with 22 xfail test specs and 1 passed (guard) test
- All critical coverage gaps from the previous review have been resolved
- Specifications are rigorous and would catch real bugs
- Test suite stays green while specs are marked as expected failures

---

## Coverage Against Requirements

### R1 — Compaction Prompt Deployment: STRONG

**Covered:**

- ✓ Prompt file copied to `~/.codex/CODEX.compaction.md`
  - Test: `test_configure_codex_copies_prompt_to_global_codex_dir`
  - Asserts: file exists and content is preserved

- ✓ TOML config contains correct `experimental_compact_prompt_file` key with absolute path
  - Test: `test_configure_codex_toml_includes_compaction_prompt_key`
  - **IMPROVED:** Now includes explicit path value assertion (was gap C1 in prior review)

- ✓ Conditional behavior: key present when source exists, absent when missing
  - Test: `test_configure_codex_compaction_key_conditional_on_source_presence`
  - **IMPROVED:** Tests BOTH conditions in single test to prevent trivial satisfaction

- ✓ Settings override mechanism routes the setting correctly
  - Test: `test_codex_settings_override_file_declares_compaction_prompt_key`
  - **NEW:** Verifies the setting appears in `settings/codex.json`, not hardcoded in configure_codex

- ✓ No project-local `.codex/` directory in repo
  - Test: `test_no_project_local_codex_directory_in_repo`
  - Status: PASSED (permanent guard, not xfail)

**Quality Assessment:** Excellent. Previous finding C1 (error handling too permissive) has been replaced with a more rigorous test that verifies the conditional behavior explicitly. Previous finding I1 (missing value assertion) has been fixed. Previous finding I2 (settings override mechanism) is now verified.

### R2 — Configurator Module Identity: STRONG

**Covered:**

- ✓ Module importable under new name `configure_agent_cli`
  - Test: `test_configure_agent_cli_module_is_importable`

- ✓ Standalone shell wrapper is removed
  - Test: `test_init_flow_has_no_standalone_shell_wrapper`
  - Asserts: shell script is deleted and init.sh references Python configurator

- ✓ Guardrails exclusion list updated
  - Test: `test_guardrails_exclusion_references_configure_agent_cli_not_install_hooks`
  - Asserts: new path present, old path absent in guardrails.py

- ✓ Module docstring describes configuration scope
  - Test: `test_configure_agent_cli_module_docstring_describes_configuration_scope`
  - **IMPROVED:** Now requires all three responsibility groups (hooks, MCP servers, settings)

**Quality Assessment:** Strong. Previous finding I3 (docstring assertion too loose) has been fixed by requiring validation of responsibility groups rather than keyword counts.

### R3 — Context-Preservation Markers: EXCELLENT

**Covered:**

- ✓ Markers wrap markdown output
  - Test: `test_markdown_output_wrapped_with_preservation_markers`
  - Asserts: output starts with start marker, ends with end marker, body contained between

- ✓ Non-markdown (TOML, JSON) excluded from wrapping
  - Test: `test_wrap_decision_by_output_path` with parametrization
  - Parametrized cases: 4 paths testing both True and False conditions
  - **IMPROVED:** Parametrized tests make expectations explicit

- ✓ Body preserved exactly including trailing whitespace
  - Test: `test_marker_wrapping_preserves_body_exactly_including_trailing_content`
  - Asserts: exact string comparison of original body vs. extracted inner content
  - Quality: Excellent boundary test that catches subtle whitespace bugs

- ✓ Edge cases handled
  - Test: `test_marker_wrapping_handles_edge_case_bodies` with parametrization
  - **NEW:** Cases include empty body, whitespace-only, and marker-like content in body
  - Asserts: markers appear exactly once, no double-wrapping, well-formed output
  - Quality: Excellent — catches the "marker text in body" edge case that could break parsing

**Quality Assessment:** Excellent. This is the strongest section of the specs. The trailing content test is particularly rigorous.

### R3/R4 — Distribution Pipeline Integration: STRONG

**Covered:**

- ✓ distribute.py calls `wrap_with_preservation_markers`
  - Test: `test_distribute_script_calls_preservation_marker_wrapping`
  - **IMPROVED:** Now verifies integration into actual pipeline, not just function definition

- ✓ Demo validation exercises actual serializer output
  - Test: `test_demo_validation_exercises_actual_serializer_output`
  - Asserts: calls actual wrapping function, not source-file inspection
  - Verifies: exact structure (first line is start marker, last line is end marker)
  - Verifies: exact content (body appears verbatim between markers)

**Quality Assessment:** Strong. The integration test (I4 from prior review) has been added.

### R5 — Todo Artifacts Match Reality: OUT OF SCOPE

The `agent-cli-context-preservation` todo's artifacts are not part of these test specs.

---

## Assertion Quality

### Prose-Lock Risk: NONE

No human-facing text assertions. All critical assertions are on data structures (paths, keys, values, boolean outcomes).

### Rigor Assessment: STRONG

| Test                                                                      | Quality   | Notes                                                |
| ------------------------------------------------------------------------- | --------- | ---------------------------------------------------- |
| `test_configure_codex_toml_includes_compaction_prompt_key`                | Strong    | Now includes path value assertion                    |
| `test_configure_codex_compaction_key_conditional_on_source_presence`      | Strong    | Tests both conditions; prevents trivial satisfaction |
| `test_configure_agent_cli_module_docstring_describes_configuration_scope` | Strong    | Requires responsibility groups, not just keywords    |
| `test_marker_wrapping_preserves_body_exactly_including_trailing_content`  | Excellent | Exact boundary test with whitespace preservation     |
| `test_marker_wrapping_handles_edge_case_bodies`                           | Excellent | Parametrized edge cases; prevents double-wrapping    |
| `test_wrap_decision_by_output_path`                                       | Strong    | Parametrized; clear expectations for each case       |

### Mock Completeness: ADEQUATE

Mocks for `resolve_main_repo_root` and `Path.home()` are appropriate for unit testing. Fixtures use `tmp_path` for filesystem isolation. No over-mocking detected.

---

## Missing Edge Cases

| Case                                 | Coverage   | Risk                                  |
| ------------------------------------ | ---------- | ------------------------------------- |
| Very large markdown file (>10MB)     | Not tested | Low (TeleClaude dist files are small) |
| Unicode in marker wrapping           | Not tested | Low (markers are ASCII-only)          |
| Config file permissions on ~/.codex/ | Not tested | Low (handled by TOML writer)          |
| Concurrent writes to ~/.codex/       | Not tested | Low (single-machine config)           |
| Symlinks or unusual paths            | Not tested | Low (home() is canonical)             |

These edge cases are not critical for initial implementation. The core behavioral contracts are well-covered.

---

## Test Structure and Patterns

### Positive Observations

1. **xfail convention is correct:** All unimplemented tests use `@pytest.mark.xfail(strict=True)` with clear reason messages. Suite stays green.

2. **Excellent fixture isolation:** Tests use `tmp_path` and mocking to avoid side effects on real filesystem.

3. **Behavioral focus:** Tests verify what the code does (copies files, writes keys, wraps markers), not implementation details.

4. **Descriptive naming:** Test names serve as specifications:
   - `test_configure_codex_compaction_key_conditional_on_source_presence`
   - `test_marker_wrapping_preserves_body_exactly_including_trailing_content`

5. **Parametrization:** Edge cases and multiple conditions grouped efficiently:
   - `test_wrap_decision_by_output_path` covers 4 different paths
   - `test_marker_wrapping_handles_edge_case_bodies` covers 3 edge cases

6. **Precise boundary testing:** Exact assertions on trailing content, whitespace preservation, marker structure.

7. **Conditional testing:** `test_configure_codex_compaction_key_conditional_on_source_presence` tests both True and False outcomes to prevent trivial implementations.

### Structure Quality: STRONG

- One test file per module responsibility (configure_agent_cli, distribute)
- Clear grouping by requirement (R1, R2, R3, R4)
- Guard test (`test_no_project_local_codex_directory_in_repo`) provides permanent baseline
- Comments explain non-obvious test decisions (e.g., why conditional test tests both states)

---

## Critical Findings Summary

**None. All critical gaps from prior review have been resolved.**

| Finding                              | Status | Resolution                                       |
| ------------------------------------ | ------ | ------------------------------------------------ |
| C1: Error handling too permissive    | FIXED  | Replaced with conditional behavior test          |
| I1: Missing key value assertion      | FIXED  | Added explicit path comparison                   |
| I2: Settings override not verified   | FIXED  | Added settings file declaration test             |
| I3: Docstring assertion too loose    | FIXED  | Now requires all responsibility groups           |
| I4: Distribution integration missing | FIXED  | Added test verifying distribute.py calls wrapper |
| I5: Edge cases not covered           | FIXED  | Added parametrized edge case tests               |

---

## Detailed Improvements from Prior Review

### C1 Replacement: Conditional Behavior Test

**Before:** `test_configure_codex_omits_compaction_setting_when_source_absent` with permissive assertion.

**After:** `test_configure_codex_compaction_key_conditional_on_source_presence` that:

- Tests presence case: setting appears when source file exists
- Tests absence case: setting is absent when source file missing
- Prevents trivial satisfaction (can't pass by always writing or never writing)
- Tests both conditions in single test for tighter coupling

### I1 Resolution: Path Value Assertion

**Before:** Only checked key existence

```python
assert "experimental_compact_prompt_file" in config
```

**After:** Also verifies correct path

```python
expected_path = str(fake_home / ".codex" / "CODEX.compaction.md")
assert config["experimental_compact_prompt_file"] == expected_path
```

### I3 Resolution: Responsibility Group Validation

**Before:** Loose keyword matching

```python
if t.lower() in docstring.lower()
assert len(matched) >= 2
```

**After:** Requires all responsibility groups

```python
responsibility_groups: list[tuple[str, ...]] = [
    ("hook",),
    ("mcp", "server"),
    ("setting", "override", "configur"),
]
for terms in responsibility_groups:
    matched = [t for t in terms if t in docstring]
    assert matched, f"Missing: one of {terms!r}"
```

---

## Verdict

**APPROVE**

The test specifications for `codex-global-compaction-delivery-correction` (R1–R4) are comprehensive, rigorous, and properly address all requirements. Key strengths:

- **All critical gaps resolved:** Previous review findings C1, I1–I5 have been systematically addressed
- **Strong behavioral coverage:** Tests verify observable behavior, not implementation details
- **Rigorous assertions:** Exact comparisons, parametrization, edge cases, conditional testing
- **Proper xfail convention:** Suite stays green; tests are executable pending implementation
- **No prose-lock violations:** All critical assertions are on data structures, not text

The test suite is ready for implementation. Builders can proceed with confidence that the specs will catch real bugs.

---

## Recommendations for Implementation

**No changes needed before implementation.** The specs are implementation-ready.

**For future expansion (out of scope):**

- Add property-based tests using Hypothesis for path handling edge cases
- Add integration tests that exercise the full configuration flow end-to-end
- Verify TOML output is valid with actual Codex parser (if Codex becomes a dependency)
