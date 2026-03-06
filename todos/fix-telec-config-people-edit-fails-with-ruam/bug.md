# Bug: telec config people edit fails with ruamel RepresenterError on AutonomyLevel enum — save_global_config serializes AutonomyLevel.auto_notify as a Python object instead of its string value. Traceback: config_handlers.py:273 save_global_config → _atomic_yaml_write → yaml.dump fails. Repro: telec config people edit 'Maurice Faber' --proficiency expert

## Symptom

telec config people edit fails with ruamel RepresenterError on AutonomyLevel enum — save_global_config serializes AutonomyLevel.auto_notify as a Python object instead of its string value. Traceback: config_handlers.py:273 save_global_config → _atomic_yaml_write → yaml.dump fails. Repro: telec config people edit 'Maurice Faber' --proficiency expert

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-06

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
