# Review Findings: fix-telec-config-people-edit-fails-with-ruam

## Verdict: APPROVE

## Summary

One-line fix (`mode="python"` to `mode="json"` in `_model_to_dict`) is correct, minimal, and well-tested. `AutonomyLevel` is a `str, Enum` subclass; `mode="json"` converts members to their string values before ruamel.yaml serialization, preventing `RepresenterError`. The regression test exercises the exact failure path with non-default enum values that survive `exclude_defaults=True`, and verifies save/load roundtrip fidelity.

No regressions introduced. No principle violations in the changed code.

## Paradigm-Fit Assessment

1. **Data flow**: Uses established `config_handlers` data layer (save/load via `_model_to_dict` and `_atomic_yaml_write`). No bypasses.
2. **Component reuse**: Modifies existing shared function — both `save_global_config` and `save_person_config` benefit from the fix.
3. **Pattern consistency**: Follows existing serialization patterns. No new abstractions.

## Principle Violation Hunt

Reviewed changed code against design fundamentals:

- **Fallback/Silent Degradation**: No new fallbacks introduced. The fix removes a crash, not a failure signal.
- **Fail Fast**: No error handling changes. The function still raises on serialization failure.
- **DIP/Coupling/SRP**: No architectural changes. `_model_to_dict` remains a single-purpose helper.
- **YAGNI/KISS**: Fix is the minimum viable change — one parameter value.
- **Encapsulation/Immutability**: No state changes.

No principle violations found in the changed code.

## Why No Issues

1. **Paradigm-fit verified**: The fix modifies a single parameter in an existing serialization helper, using the same data flow (Pydantic model -> dict -> YAML write) established by the codebase.
2. **Requirements met**: The bug (`RepresenterError` on enum serialization) is fixed. The regression test reproduces the exact failure path and proves the fix.
3. **Copy-paste duplication checked**: No duplication. The fix benefits both `save_global_config` and `save_person_config` through the shared `_model_to_dict` function.
4. **Side effect analysis**: `mode="json"` vs `mode="python"` was analyzed against all types in `GlobalConfig` and `PersonConfig` schemas. No `Path`, `datetime`, `Decimal`, `bytes`, `UUID`, or `set` fields exist — all schema types serialize identically or more correctly under `mode="json"`.

## Critical

(none)

## Important

(none)

## Suggestions

1. **Test coverage gap — `by_cartridge` and `by_event_type` not exercised** (`test_config_handlers.py:155-179`): The regression test populates `global_default` and `by_domain` but not the other two `AutonomyLevel`-typed dict fields on `AutonomyMatrix`. Low severity since the code path is shared, but future maintainers cannot tell from tests alone that those fields are safe.

2. **Pre-existing: silent flock failure** (`config_handlers.py:242-245`): `_atomic_yaml_write` catches `OSError` on `fcntl.flock` with bare `pass`. Not introduced by this fix, but worth noting as a follow-up improvement — a `logger.warning` would make lock failures visible.

3. **Pre-existing: broad exception catch in `find_person_by_invite_token`** (`config_handlers.py:344-350`): `except Exception` hides `PermissionError` and other non-schema failures as routine warnings. Not in scope of this fix.

## Demo Artifact

No `demo.md` present. For a one-line internal serialization fix with a comprehensive regression test, the absence is acceptable — the fix is not user-facing in a way that benefits from demo blocks (the CLI command simply stops crashing).

## Manual Verification Evidence

Manual CLI verification was not performed in the review environment. The regression test (`test_save_global_config_with_autonomy_level_enum`) exercises the exact failure path end-to-end through save and load, which provides equivalent confidence for this internal serialization fix.
