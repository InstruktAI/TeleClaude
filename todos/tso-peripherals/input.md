# Input: tso-peripherals

Parent: test-suite-overhaul

## Problem

Many small modules have no dedicated tests or have tests scattered in the flat `tests/unit/` directory. These are individually small but collectively represent ~100 source files that need 1:1 mapping.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/channels/` (6 files)
- `teleclaude/chiptunes/` (8 files)
- `teleclaude/cron/` (6 files)
- `teleclaude/deployment/` (4 files)
- `teleclaude/helpers/` (4 + 1 youtube = 5 files)
- `teleclaude/history/` (2 files)
- `teleclaude/install/` (2 files)
- `teleclaude/memory/` (6 + 4 context = 10 files)
- `teleclaude/mirrors/` (7 files)
- `teleclaude/output_projection/` (5 files)
- `teleclaude/project_setup/` (10 files)
- `teleclaude/runtime/` (2 files)
- `teleclaude/stt/` (1 + 3 backends = 4 files)
- `teleclaude/tagging/` (2 files)
- `teleclaude/tools/` (1 file)
- `teleclaude/tts/` (5 + 6 backends = 11 files)
- `teleclaude/types/` (4 files)
- `teleclaude/utils/` (4 files)
- `teleclaude/` root files (19 files: daemon.py, constants.py, logging_config.py, mcp_server.py, etc.)

Total: ~112 source files

Many of these will be trivially handled:
- `__init__.py` files with only imports go to `ignored.md`
- Constants/enums/type definitions go to `ignored.md`
- Small modules with 1-2 public functions get quick behavioral tests

Prioritize modules with business logic (memory, mirrors, cron, output_projection) over data-only modules.

## Worker procedure

For each source file:
1. Quick assessment: is this testable or exempt? (`__init__.py`, pure constants, type-only)
2. If exempt, add to `ignored.md` with reason
3. If testable, read public interface, find existing tests, triage, create 1:1 test
4. Each test function gets a behavioral contract docstring

## Constraints

- No source files modified
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions
- For STT/TTS backends: mock the external API boundary, test the adapter contract
- For daemon.py: test lifecycle contracts, not subprocess details

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- All new tests pass
- All tests have behavioral docstrings
- `ignored.md` is comprehensive and well-documented for exempt files
