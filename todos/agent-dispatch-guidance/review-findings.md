# Review Findings: agent-dispatch-guidance

**Review round:** 1
**Reviewer:** Claude (automated)
**Date:** 2026-02-21

---

## Critical

_None._

## Important

### R1-F1: `compose_agent_guidance` silently returns empty agent list when all agents are runtime-unavailable

**File:** `teleclaude/core/next_machine/core.py:1211-1238`

`enabled_count` is incremented _before_ the runtime availability check. If all config-enabled agents are simultaneously `unavailable` in the DB, the function returns a guidance block with header + thinking modes but **zero agents listed**. The `enabled_count == 0` guard only catches config-disabled agents.

The old `get_available_agent()` handled this case by returning the soonest-to-recover agent. The new code silently produces empty guidance, which could confuse the orchestrator AI into making an invalid selection.

**Fix:** Track a separate `listed_count` after the availability filter, or decrement `enabled_count` when skipping unavailable agents. Raise `RuntimeError` when no agents survive the runtime filter.

```python
# After the for loop, add:
listed_count = sum(1 for line in lines if line.startswith("- "))
if listed_count == 0:
    raise RuntimeError("No agents are currently enabled and available.")
```

### R1-F2: Implementation plan Task 3.1 checkboxes are unchecked despite work being completed

**File:** `todos/agent-dispatch-guidance/implementation-plan.md:74-77`

Phase 3 / Task 3.1 has three unchecked items:

- `[ ] Remove test_get_available_agent_skips_degraded`
- `[ ] Update mocks from get_available_agent → compose_agent_guidance`
- `[ ] All existing tests pass`

Inspection of the diff confirms all three were actually completed (test removed from `test_next_machine_breakdown.py`, mocks updated in deferral/state_deps tests). The checkboxes just weren't marked.

**Fix:** Mark the three items as `[x]`.

## Suggestions

### R1-F3: `AgentDispatchConfig` Pydantic model is defined but unused in config loading

**File:** `teleclaude/config/schema.py:6-10`

`AgentDispatchConfig` is defined as a Pydantic validation model but never imported or used in `_build_config()`. The actual fields (`enabled`, `strengths`, `avoid`) are added directly to the `AgentConfig` dataclass and read from raw dicts. The model only serves as documentation and is tested in `test_agent_dispatch_config.py`.

Consider either wiring it into validation or removing it to avoid dead code confusion. Not blocking.

### R1-F4: Repeated `compose_agent_guidance` calls within a single `next_work` invocation

**File:** `teleclaude/core/next_machine/core.py:2063-2153`

Each dispatch branch (build, review, fix, defer, finalize) independently calls `compose_agent_guidance(db)`, which queries the DB for every agent's availability each time. In `next_work`, only one branch executes per call so there's no _correctness_ issue, but the pattern of wrapping every call in its own try/except is repetitive. A single call at the top of the dispatch section (after precondition checks) would simplify the code. Not blocking — current structure is correct.

### R1-F5: `api_server.py` change adds config.enabled check outside the scope boundary

**File:** `teleclaude/api_server.py:955-964`

The agent availability API endpoint now returns `status="unavailable"` with `reason="Disabled in config.yml"` for config-disabled agents. This is a good addition that aligns the API with config, but it's not listed in the requirements or implementation plan scope. It's a sensible bonus change — just noting it wasn't formally scoped.

---

## Requirements Tracing

| Requirement                                                          | Status                                                                                                                                                                    |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config.yml` has `agents` section with `enabled`/`strengths`/`avoid` | **Implemented** — `config.sample.yml`, `tests/integration/config.yml`, `AgentConfig` dataclass                                                                            |
| No hardcoded fallback matrices remain in `core.py`                   | **Implemented** — `WORK_FALLBACK`, `PREPARE_FALLBACK`, `get_available_agent()`, `_pick_agent()` all deleted                                                               |
| `format_tool_call` output includes guidance block with placeholders  | **Implemented** — `guidance` param replaces `agent`/`thinking_mode`, output has `<your selection>`                                                                        |
| Disabled agents do not appear in guidance                            | **Implemented** — `compose_agent_guidance` skips `not cfg.enabled`                                                                                                        |
| Degraded agents noted with status                                    | **Implemented** — `[DEGRADED: reason]` annotation                                                                                                                         |
| All existing tests pass after migration                              | **Implemented** — mocks updated, old test removed (but plan checkboxes unchecked: R1-F2)                                                                                  |
| New unit tests cover `compose_agent_guidance` and `format_tool_call` | **Implemented** — `test_agent_guidance.py` (5 tests), `test_agent_config_loading.py` (2 tests), `test_agent_dispatch_config.py` (3 tests), `test_agent_cli.py` (+2 tests) |
| `agent_cli._pick_agent` respects `config.agents.enabled`             | **Implemented** — config check added with tests                                                                                                                           |
| Backwards compatible (missing agents section defaults)               | **Implemented** — `AgentConfig` defaults: `enabled=True`, `strengths=""`, `avoid=""`                                                                                      |

## Test Coverage Assessment

- **New coverage is solid:** `compose_agent_guidance` has tests for all-available, degraded, unavailable, and no-agents-enabled scenarios.
- **Missing edge case:** No test for all agents config-enabled but all runtime-unavailable (R1-F1).
- **Config loading coverage:** `_build_config` tested for defaults and overrides — good.
- **agent_cli coverage:** Config-disabled agent selection properly tested with both auto-pick and preferred-agent paths.
- **Migrated tests:** Mocks correctly updated from `get_available_agent` (returning tuple) to `compose_agent_guidance` (returning string).

---

## Verdict

- [x] REQUEST CHANGES

**Blocking:** R1-F1 (empty guidance when all agents runtime-unavailable) and R1-F2 (unchecked implementation plan items).

R1-F1 is a behavioral regression from the old code. R1-F2 is a clerical issue that must be fixed for the quality checklist to be accurate.
