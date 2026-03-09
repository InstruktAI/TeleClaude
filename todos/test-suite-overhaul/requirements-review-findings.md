# Requirements Review Findings: test-suite-overhaul

## Auto-remediated (resolved)

### 1. Missing `[inferred]` markers — Important (resolved)

Several requirements were inferred from the input's problem description but presented as
explicit requirements. Added `[inferred]` markers to:

- Mirror-path naming convention (`tests/unit/<mirror-path>/test_<name>.py`)
- Zero hard-coded string assertions threshold (derived from 81.6% problem)
- `@patch` decorator limit of 5 (derived from 15+ problem)
- Test function docstring requirement (derived from "TDD behavioral contracts" intent)
- CI enforcement scope item (not present in input at all)

The human should review these inferences — especially the docstring requirement, which
adds meaningful work not explicitly requested.

### 2. Source file count corrected — Suggestion (resolved)

Requirements stated 351 source files; actual count is 354. Updated to ~354.

## Unresolved

### 3. CI enforcement lacks success criterion — Suggestion

"CI enforcement (1:1 mapping check)" is listed in scope but has no corresponding
success criterion. The builder won't know what artifact to produce — a pytest plugin,
a pre-commit hook, a CI pipeline step, or a standalone script. Consider adding a
success criterion like:

> A CI check validates the 1:1 mapping and fails if an unmapped source file exists
> without an entry in `tests/ignored.md`.

### 4. "Cross-module workflows" distinction is subjective — Suggestion

The criterion "Integration tests in tests/integration/ test cross-module workflows,
not unit-level behavior" lacks a concrete heuristic. A builder can't mechanically
verify this. Consider a measurable proxy such as "imports from 2+ teleclaude
subpackages" or "exercises a chain spanning 2+ components."

### 5. Known failing tests handling is implicit — Suggestion

`tests/ignored.md` documents two known failing tests that are currently skipped in
gate validation. The success criterion "All tests pass" is satisfied if they remain
`@pytest.mark.skip`-ed, but the requirements don't explicitly state whether this work
should fix, remove, or preserve them. Since the input says "tests only, never source
logic," fixing the root cause (test infrastructure) may be in scope, but this is
ambiguous.
