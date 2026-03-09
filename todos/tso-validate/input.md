# Input: tso-validate

Parent: test-suite-overhaul

## Problem

After all workers and integration triage complete, the full suite needs validation against every success criterion from the parent requirements.

## Scope

- Full test suite execution (`pytest tests/`)
- CI enforcement script validation (1:1 mapping check)
- `tests/ignored.md` completeness audit
- Success criteria verification from parent requirements

## Worker procedure

1. Run full test suite: `pytest tests/` must exit 0
2. Run CI enforcement script: validate 1:1 mapping, report any gaps
3. Audit `tests/ignored.md`:
   - Every entry has a valid reason
   - No entries for files that now have tests
   - No source files missing from both tests and ignored.md
4. Verify success criteria:
   - [ ] Every source file has 1:1 test or is in ignored.md
   - [ ] Zero orphan test files
   - [ ] Zero hard-coded string assertions
   - [ ] No test function with >5 `@patch` decorators
   - [ ] Every test function has a behavioral docstring
   - [ ] No source file behavior changed
   - [ ] Integration tests are genuinely cross-module
   - [ ] CI check validates the mapping
   - [ ] Known failing tests resolved or documented
5. Produce a validation report with pass/fail per criterion

## Constraints

- No source files modified
- No test modifications — validation only (report issues back to relevant worker todo)
- If criteria fail, create follow-up remediation tasks

## Success criteria

- All parent success criteria pass
- Validation report produced
- Feature branch is ready for integration to main
