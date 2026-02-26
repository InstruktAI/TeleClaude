# Review Findings: deployment-cleanup

## Review Round 1

### Paradigm-Fit Assessment

- **Data flow**: Clean removal following the event bus → handler → service chain. Consumers removed before providers (API endpoint → daemon handler → service → events). PASS.
- **Component reuse**: No copy-paste duplication. Test substitutions use semantically equivalent tools (`telec agents status` replaces `telec deploy` in role filtering tests — both are member-excluded). PASS.
- **Pattern consistency**: Follows existing patterns for system commands, tool access filtering, CLI surface definitions. PASS.

### Critical

(none)

### Important

1. **Orphaned `telec deploy` section in global CLI spec** — `docs/global/general/spec/tools/telec-cli.md:42-44`
   still contains a `### telec deploy` heading with `<!-- @exec: telec deploy -h -->`.
   Since the command no longer exists, `telec sync` will fail or produce broken output
   for this section. Remove lines 42-44. This violates the requirement: "All docs
   reference the new automated deployment flow."

### Suggestions

2. **Stale "deploy" in `send_system_command` docstring** — `teleclaude/transport/redis_transport.py:1863,1867`
   still mentions "deploy" as an example system command. Should use "health_check" instead.

3. **Stale "deploy" in `_handle_system_command` docstring** — `teleclaude/daemon.py:1122`
   still says `System commands are daemon-level operations (deploy, restart, etc.)`.
   Deploy is no longer a system command.

### Requirements Trace

| Requirement                                          | Status                                        |
| ---------------------------------------------------- | --------------------------------------------- |
| `telec deploy` MCP tool removed                      | PASS (MCP already removed by prior migration) |
| No deploy dispatch path in daemon/transport          | PASS                                          |
| `deploy_service.py` deleted                          | PASS                                          |
| `DeployArgs` removed from `core/events.py`           | PASS                                          |
| Deploy status check removed from `core/lifecycle.py` | PASS                                          |
| All docs reference automated deployment flow         | **FAIL** — global CLI spec still has deploy   |
| New `deployment-pipeline.md` exists                  | PASS                                          |
| `make lint` and `make test` pass                     | PASS (builder: 2349 passed, 106 skipped)      |

### Test Coverage Assessment

- Tests updated: `test_api_route_auth.py`, `test_role_tools.py`, `test_help_desk_features.py`, `test_contracts.py`
- Role filtering tests correctly substituted `telec agents status` (member-excluded tool) for removed `telec deploy`
- Config contract test updated to include `deployment` key
- Regression risk: Low — removal is clean, no new behavior introduced

Verdict: **REQUEST CHANGES**

---

## Review Round 2

### Status of Round 1 Findings

| #   | Severity   | Finding                                                                                | Status                          |
| --- | ---------- | -------------------------------------------------------------------------------------- | ------------------------------- |
| 1   | Important  | Orphaned `telec deploy` section in `docs/global/general/spec/tools/telec-cli.md:42-44` | **OPEN** — still present        |
| 2   | Suggestion | Stale "deploy" in `send_system_command` docstring (`redis_transport.py:1863,1867`)     | OPEN (suggestion, non-blocking) |
| 3   | Suggestion | Stale "deploy" in `_handle_system_command` docstring (`daemon.py:1122`)                | OPEN (suggestion, non-blocking) |

### New Findings

#### Important

1. **Round 1 Important #1 remains unresolved** — `docs/global/general/spec/tools/telec-cli.md:42-44` still contains:

   ```
   ### `telec deploy`

   <!-- @exec: telec deploy -h -->
   ```

   Since the command no longer exists, `telec sync` will fail or produce broken output. Remove these lines.

2. **Stale comment referencing deploy commands** — `teleclaude/transport/redis_transport.py:1038`:
   ```
   # This is critical for deploy commands that call os._exit(0)
   ```
   The deploy service that called `os._exit(42)` is deleted. This comment references the old system. Update to reference the general restart pattern or the new deployment executor.

#### Suggestions

(Same as Round 1 — stale "deploy" examples in docstrings at `daemon.py:1122` and `redis_transport.py:1863,1867`. Recommended to fix alongside the Important findings for a clean sweep.)

### Requirements Trace (Round 2)

| Requirement                                  | Status                                                                            |
| -------------------------------------------- | --------------------------------------------------------------------------------- |
| All docs reference automated deployment flow | **FAIL** — `docs/global/general/spec/tools/telec-cli.md` still has `telec deploy` |
| All other requirements                       | PASS (unchanged from Round 1)                                                     |

### Test Coverage Assessment

No change from Round 1. Tests correctly updated, regression risk low.

Verdict: **REQUEST CHANGES**

Fix: Remove lines 42-44 from `docs/global/general/spec/tools/telec-cli.md` and update the stale comment at `redis_transport.py:1038`. Optionally clean up the suggestion-level docstring references.
