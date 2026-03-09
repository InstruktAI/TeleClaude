# DOR Report: multi-user-config

## Draft Assessment (not a formal gate verdict)

### Gate 1: Intent & Success -- PASS

The problem is clear: monolithic config prevents multi-user deployments. The goal is well-defined: three config layers with merge semantics, isolation, and backward compatibility. Success criteria are concrete and testable.

### Gate 2: Scope & Size -- PASS

This is scoped to config loading changes and a split migration tool. No database changes, no service management, no identity resolution. Fits a single AI session. The implementation plan has 10 tasks across 4 phases -- substantial but within scope.

### Gate 3: Verification -- PASS

Each requirement has a corresponding test:

- Layer merging tested with sample configs
- Override restrictions tested with invalid per-user configs
- Secrets isolation tested with API key patterns
- Permission checks tested with mocked `os.stat`
- Backward compatibility verified by running existing test suite

### Gate 4: Approach Known -- PASS

The technical path is well-understood:

- Existing `_deep_merge` function handles YAML merging
- Pydantic models handle validation (existing pattern in codebase)
- File permission checks are standard `os.stat` calls
- Config discovery is file-existence checks
- The config split is key classification + file writing

No novel patterns required. All techniques are already used in the codebase.

### Gate 5: Research Complete -- PASS

No third-party dependencies introduced. All libraries already in use (PyYAML, Pydantic, `pathlib`, `os`). Platform detection via `sys.platform` is well-documented.

### Gate 6: Dependencies & Preconditions -- NEEDS WORK

- **Depends on Phase 1 (`multi-user-identity`)**: In system-wide mode, the daemon needs to know which OS user is connecting to load the correct per-user config. Without identity resolution, the daemon can only load per-user config for the process owner (sufficient for single-user mode, but not for system-wide).
- **Partial independence**: The config layer infrastructure (system + secrets loading) can be built without Phase 1. Only the per-user config loading for non-process-owner users requires identity resolution.
- **Mitigation**: Build the layer infrastructure assuming process-owner for per-user config. Phase 1 integration adds the UID-to-username mapping later.

### Gate 7: Integration Safety -- PASS

- Single-user mode is the unchanged default path -- extracted into its own function with no behavioral change.
- System mode activates only when the system config file exists -- opt-in.
- The final `Config` object is identical in both modes -- downstream code sees no difference.
- Incremental merge to main is safe.

### Gate 8: Tooling Impact -- N/A

No tooling or scaffolding changes.

## Assumptions

1. The existing `_deep_merge` function correctly handles nested dict merging for all config shapes in use.
2. Pydantic model validators can enforce the per-user allow-list without breaking existing `PersonConfig` usage.
3. The secrets-to-environment bridge (setting env vars from secrets file) does not cause side effects in code that reads env vars at import time.
4. File permission checks via `os.stat` work correctly on both macOS and Linux.

## Open Questions

1. **Platform paths**: macOS `/usr/local/etc/teleclaude/` vs Linux `/etc/teleclaude/` -- use `sys.platform` for detection. This is a straightforward decision, not a blocker.
2. **Per-user per-project overrides**: Should per-user config support project-specific sections? Recommendation: defer to a follow-up. Start with global per-user preferences only.
3. **Secrets file vs `.env` precedence**: Environment variables always win. Secrets file fills in what env vars don't provide. `.env` loading happens before secrets file loading.

## Score: 6/10

**Status: needs_work**

The approach and scope are solid, but the dependency on Phase 1 for full per-user config loading is a blocker for the complete feature. The config layer infrastructure (system + secrets) can be built independently, but per-user config for arbitrary OS users requires identity resolution.

**Blockers:**

- Depends on Phase 1 (`multi-user-identity`) for per-user config loading in system-wide mode
- Config hierarchy layer specification needs exact definition of which keys belong to which layer (the allow-list must be finalized before build)
