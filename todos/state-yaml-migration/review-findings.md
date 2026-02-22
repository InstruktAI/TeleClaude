# Review Findings: state-yaml-migration

## Verdict: APPROVE

The implementation correctly migrates the todo state serialization from JSON to YAML format. All requirements were implemented, backward compatibility was added, tests were updated, and code quality is maintained.

## Critical Issues

None.

## Important Issues

### R1-F1: roadmap.yaml header comment not updated

**Location:** `todos/roadmap.yaml:1`

**Issue:** The header comment still reads:

```
# Priority order (first = highest). Per-item state in {slug}/state.json.
```

But should read:

```
# Priority order (first = highest). Per-item state in {slug}/state.yaml.
```

**Analysis:** The `save_roadmap()` function at `teleclaude/core/next_machine/core.py:713` correctly writes the updated header with "state.yaml". However, the existing `roadmap.yaml` file retains the old header text because it hasn't been rewritten since the migration. The file is only rewritten when roadmap entries are added/removed/moved.

**Impact:** Cosmetic only. The code is correct, but the file's header comment is stale documentation.

**Fix:** Manually update the header comment in `todos/roadmap.yaml`, or trigger a roadmap rewrite by moving an entry and moving it back.

## Suggestions

### R1-S1: Cleanup untracked state.json

**Location:** `todos/state-yaml-migration/state.json`

**Issue:** An untracked `state.json` file exists in the `state-yaml-migration` directory.

**Recommendation:** Remove this file - it's a leftover that should have been cleaned up.

```bash
rm todos/state-yaml-migration/state.json
```

### R1-S2: Consider adding backward compatibility test

**Issue:** While backward compatibility is implemented (state.yaml falls back to state.json), there's no explicit test for this fallback behavior.

**Recommendation:** Add a test case that:

1. Creates a todo with only `state.json` (no `state.yaml`)
2. Verifies `read_phase_state()` correctly reads from `state.json`
3. Verifies the fallback path works as expected

This would document the fallback behavior and prevent regression.

### R1-S3: Test failure unrelated to migration

**Location:** `tests/unit/test_install_hooks.py:67`

**Issue:** Test `test_configure_claude_never_embeds_worktree_path` fails with:

```
assert 'trees/' not in '/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/state-yaml-migration/...'
```

**Analysis:** This is NOT a regression from the state-yaml-migration changes. The test file was not modified in this branch. The test is environment-sensitive and fails when the test suite runs from inside a worktree (because `Path(__file__).resolve()` returns the worktree path which contains "trees/").

**Impact:** Does not block this migration. This is a pre-existing test issue that should be addressed separately.

**Recommendation:** File a separate issue for fixing this environment-sensitive test.

## Requirements Tracing

All requirements from `requirements.md` were implemented:

- ✅ Renamed all code references from `state.json` to `state.yaml`
- ✅ Updated central read/write functions (`get_state_path`, `read_phase_state`, `write_phase_state`)
- ✅ Updated scaffold to generate `state.yaml`
- ✅ Updated validation to expect `state.yaml` (with fallback)
- ✅ Updated `roadmap.py` to read `state.yaml` (with fallback)
- ✅ Updated worktree sync file lists
- ✅ Updated `sweep_completed_groups` to read `state.yaml` (with fallback)
- ✅ Updated `todo_watcher.py` docstring
- ✅ Migrated all 34 existing `state.json` files to `state.yaml`
- ✅ Added backward-compat fallback (state.yaml → state.json)
- ✅ Updated all unit/integration tests
- ⚠️ Updated `roadmap.yaml` header comment (code is correct, file is stale - see R1-F1)
- ✅ Updated `save_roadmap` header in `core.py`
- ✅ Updated agent command docs
- ✅ Updated doc snippets

## Code Quality Assessment

### Strengths

1. **Consistent fallback pattern**: The backward compatibility implementation is consistent across all read functions:

   ```python
   state_path = get_state_path(cwd, slug)  # returns state.yaml
   if not state_path.exists():
       legacy_path = state_path.with_name("state.json")
       if legacy_path.exists():
           state_path = legacy_path
   ```

2. **Proper YAML configuration**: Uses appropriate YAML dump settings:

   ```python
   yaml.dump(state, default_flow_style=False, sort_keys=False)
   ```

   This produces readable output without flow style and preserves key order.

3. **Complete migration**: All 34 state.json files were migrated and removed from git.

4. **Comprehensive test updates**: All test files that referenced state.json were updated to use state.yaml.

5. **Error handling**: Proper exception handling for `yaml.YAMLError` where `json.JSONDecodeError` was previously used.

### Type Safety

No type errors. All YAML operations use `yaml.safe_load()` (not `yaml.load()`) which is the security best practice.

### Linting

`make lint` passes with no violations related to this change.

### Test Coverage

All tests pass except for one pre-existing environment-sensitive test unrelated to this migration.

## Security Assessment

No security issues. The migration:

- Uses `yaml.safe_load()` instead of `yaml.load()` (prevents arbitrary code execution)
- Does not introduce any new attack surface
- Maintains existing validation and error handling

## Summary

This is a clean, well-executed serialization format migration. The implementation is consistent, the backward compatibility pattern is sound, and all tests were properly updated. The only important finding (R1-F1) is cosmetic and does not affect functionality.

**Recommendation: APPROVE**
