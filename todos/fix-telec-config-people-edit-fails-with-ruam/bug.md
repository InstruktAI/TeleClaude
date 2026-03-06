# Bug: telec config people edit fails with ruamel RepresenterError on AutonomyLevel enum — save_global_config serializes AutonomyLevel.auto_notify as a Python object instead of its string value. Traceback: config_handlers.py:273 save_global_config → _atomic_yaml_write → yaml.dump fails. Repro: telec config people edit 'Maurice Faber' --proficiency expert

## Symptom

telec config people edit fails with ruamel RepresenterError on AutonomyLevel enum — save_global_config serializes AutonomyLevel.auto_notify as a Python object instead of its string value. Traceback: config_handlers.py:273 save_global_config → _atomic_yaml_write → yaml.dump fails. Repro: telec config people edit 'Maurice Faber' --proficiency expert

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-06

## Investigation

Traced the failure path:
1. `telec config people edit 'Maurice Faber' --proficiency expert` calls `save_global_config(config)` in `config_cli.py:331`.
2. `save_global_config` calls `_model_to_dict(config)` which calls `model.model_dump(mode="python", exclude_defaults=True)`.
3. With `mode="python"`, Pydantic returns Python objects including enum instances (e.g., `AutonomyLevel.auto_notify`).
4. If `GlobalConfig.event_domains` is set and contains `AutonomyMatrix` with non-default `AutonomyLevel` values, those enum objects appear in the serialized dict.
5. `_atomic_yaml_write` passes the dict to ruamel.yaml's `yaml.dump()`, which cannot represent Python enum objects.
6. ruamel.yaml raises `RepresenterError`.

## Root Cause

`_model_to_dict` in `teleclaude/cli/config_handlers.py` used `mode="python"` in `model.model_dump(...)`. This returns Python-native types including enum instances. ruamel.yaml has no representer for `AutonomyLevel` enum objects, causing a `RepresenterError` during serialization.

## Fix Applied

Changed `mode="python"` to `mode="json"` in `_model_to_dict`. With `mode="json"`, Pydantic serializes all values to JSON-native equivalents: enums become their string values, which ruamel.yaml can serialize natively.

Files changed:
- `teleclaude/cli/config_handlers.py`: one-line fix (`mode="python"` → `mode="json"`)
- `tests/unit/test_config_handlers.py`: added regression test `test_save_global_config_with_autonomy_level_enum` that reproduces the failure and verifies the fix.
