# DOR Report: agent-dispatch-guidance

## Assessment

Gate phase — formal DOR validation (2026-02-21).

## Gate Results

| Gate                            | Verdict  | Evidence                                                                                                                                                                                                                   |
| ------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Intent & success             | **Pass** | Problem explicit in input.md. 7 testable success criteria in requirements.md. Outcome: guidance replaces matrices.                                                                                                         |
| 2. Scope & size                 | **Pass** | Single concern. 11 format_tool_call call sites, 7 get_available_agent call sites, 5 test files. Mechanical rewiring — fits one session.                                                                                    |
| 3. Verification                 | **Pass** | Unit tests for compose_agent_guidance (4 cases: all enabled, disabled, degraded, single). Tests for format_tool_call (guidance placeholder, no hardcoded agent). make test as final gate.                                  |
| 4. Approach known               | **Pass** | Pattern: Pydantic model + dataclass fields + overlay in \_build_config + composition function + call site rewiring. All proven patterns in this codebase. 5 architectural decisions resolved in input.md.                  |
| 5. Research complete            | **Pass** | No third-party dependencies. Automatically satisfied.                                                                                                                                                                      |
| 6. Dependencies & preconditions | **Pass** | No roadmap dependencies. All target files verified present: core.py, config/**init**.py, config/schema.py, config.yml, agent_cli.py, 2 doc snippets. Config import pattern exists in handlers.py:24.                       |
| 7. Integration safety           | **Pass** | Backwards compatible: missing agents section defaults to all enabled with empty strengths. \_validate_disallowed_runtime_keys guard removal is safe — overlay only reads enabled/strengths/avoid, ignoring any extra keys. |
| 8. Tooling impact               | **N/A**  | No tooling or scaffolding changes.                                                                                                                                                                                         |

## Verified Claims

- `WORK_FALLBACK` at line 78, `PREPARE_FALLBACK` at line 70, `get_available_agent` at line 1260, `_pick_agent` at line 2027 — all confirmed present for deletion
- `format_tool_call` at line 176 — confirmed takes `agent` and `thinking_mode` params
- `AgentConfig` at line 124 — confirmed @dataclass, no field conflicts with enabled/strengths/avoid
- `_validate_disallowed_runtime_keys` at line 430 — confirmed blocks "agents" key in config.yml; guard removal is safe because overlay reads only dispatch fields
- Test files confirmed: test_next_machine_breakdown.py (line 186), test_next_machine_state_deps.py (line 514), test_next_machine_deferral.py (lines 100, 142), test_agent_cli.py (6 \_pick_agent tests), test_daemon_independent_jobs.py (4 monkeypatches)
- Doc snippets confirmed: docs/project/spec/teleclaude-config.md, docs/project/design/architecture/next-machine.md

## Refinement Applied

- Task 2.3: added exact call site counts (5 in next_work, 6 in next_prepare) and explicit config import pattern reference (handlers.py:24)

## Overall Verdict

**Pass** — Score: 9/10

Ready for build.
