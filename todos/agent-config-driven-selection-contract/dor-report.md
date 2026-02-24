# DOR Report: agent-config-driven-selection-contract

## Gate Assessment (Final)

### Gate 1: Intent & Success — PASS

Problem statement is explicit: config-driven agent selection with fail-closed behavior. Six concrete acceptance criteria, all testable. No ambiguity in success definition.

### Gate 2: Scope & Size — PASS

Cross-cutting across config, dispatch, MCP, API, and TUI surfaces. Bounded to agent-selection policy only. Five phases provide natural session boundaries. Verified ~35+ hardcoded agent lists exist — scope is real but contained.

### Gate 3: Verification — PASS

Verification plan lists specific test commands per phase. Observable behaviors are described for each requirement. Edge cases documented (leading `/` in `run_agent_command`, visual theming constants, new provider onboarding).

### Gate 4: Approach Known — PASS

Pattern is established: centralize helpers in `core/agents.py`, migrate call sites incrementally. All target files exist and patterns are well-understood. `AgentName` enum already exists (in two places — builder consolidates).

### Gate 5: Research Complete — PASS (auto-satisfied)

No third-party dependencies introduced.

### Gate 6: Dependencies & Preconditions — PASS

Logical dependency `adapter-output-delivery` delivered (2026-02-24, commit `21544a6d`). No roadmap blockers.

### Gate 7: Integration Safety — PASS

Incremental rollout: helper APIs first (Phase 2), then call-site migration (Phase 3-4). Rollback is module-level containment. No data migrations.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

No scaffolding or tooling procedure changes required.

## Plan-to-Requirement Fidelity (Final)

| Requirement                         | Phase       | Verified                                                                                                                                                              |
| ----------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1 (config authoritative)           | Phase 1     | Config load path at `config/__init__.py:601` currently silent-defaults `agents` to `{}`. Phase 1 adds fail-fast validation. Correct.                                  |
| R2 (centralized identifiers/policy) | Phase 2     | No `is_agent_enabled`/`get_enabled_agents`/`get_known_agents` helpers exist today. Plan creates them in `core/agents.py`. Correct.                                    |
| R3 (enforced selection contract)    | Phase 3     | MCP server delegates to `mcp/handlers.py` — no bypass paths. Plan correctly marks `mcp_server.py` as conditional. Correct.                                            |
| R4 (guidance quality)               | Phase 4     | `compose_agent_guidance` (`core/next_machine/core.py:1366`) already checks `cfg.enabled` but doesn't placeholder empty strengths/avoid. Plan addresses this. Correct. |
| R5 (TUI/availability surfaces)      | Phase 4     | `modals.py:250` has `_AGENTS = ("claude", "gemini", "codex")` hardcoded. Plan targets this. Correct.                                                                  |
| R6 (backward compatibility)         | Phases 1, 3 | Error messages pointing to `config.yml` keys specified in requirements and plan. Correct.                                                                             |

No contradictions found between plan and requirements.

## Resolved Open Questions

1. **MCP server bypass paths:** `mcp_server.py:439-460` delegates entirely to handler methods in `mcp/handlers.py`. No enforcement changes needed in `mcp_server.py` itself.
2. **Zero-enabled TUI blocking tests:** No existing coverage. Plan Phase 5 correctly includes `test_tui_modal.py` and `test_tui_agent_status.py` for this behavior.

## Implementation Notes for Builder

- `AgentName` enum exists in both `core/agents.py:11` and `helpers/agent_types.py:6`. Consolidate to one canonical location during Phase 2.
- `api_models.py` contains `Literal["claude", "gemini", "codex"]` type annotations. These are validation boundaries, not runtime selection logic — leave as-is per R2 scope ("selection/dispatch code").
- `teleclaude/cli/tui/theme.py` color palettes are explicitly out of scope per requirements edge-case documentation.

## Gate Verdict

- **Score:** 8/10
- **Status:** `pass`
- **Blockers:** None
- **Ready for implementation.**
