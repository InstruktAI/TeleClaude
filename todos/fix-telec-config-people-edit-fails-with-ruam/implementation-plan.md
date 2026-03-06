# Implementation Plan: telec config people edit RepresenterError

## Objective
Fix `telec config people edit` command failing with ruamel.yaml RepresenterError when AutonomyLevel enum values are present in configuration.

## Root Cause
`_model_to_dict()` in `teleclaude/cli/config_handlers.py` used `mode="python"` in `model.model_dump()`, causing Pydantic to return Python enum objects. ruamel.yaml cannot serialize these enum objects, raising `RepresenterError`.

## Solution
Change serialization mode from `"python"` to `"json"` so that enum values are converted to their string equivalents before being passed to ruamel.yaml.

## Changes
1. **teleclaude/cli/config_handlers.py** (line 266)
   - Changed: `mode="python"` → `mode="json"` in `_model_to_dict()`

2. **tests/unit/test_config_handlers.py**
   - Added regression test `test_save_global_config_with_autonomy_level_enum()` that:
     - Creates a GlobalConfig with non-default AutonomyLevel enum values
     - Verifies save succeeds without RepresenterError
     - Verifies loaded config preserves enum values

## Verification
- Unit tests pass: 3186 passed, 5 skipped
- Regression test validates the specific enum serialization issue
- No new linting issues introduced
