# Implementation Plan — agent-config-driven-selection-contract

## Objective

Implement fail-closed, config-driven agent selection and enforcement. Remove hardcoded agent-list sprawl from selection/dispatch surfaces and centralize policy in one runtime contract.

## Requirement Traceability

- R1 (config authoritative) -> Phase 1.
- R2 (centralized identifiers/policy) -> Phase 2.
- R3 (enforced selection contract) -> Phase 3.
- R4 (next-machine guidance quality) -> Phase 4.
- R5 (TUI/availability surfaces) -> Phase 4.
- R6 (migration clarity/backward compatibility) -> Phases 1 and 3.

## Phase 1 — Config Contract and Validation

- [x] Require explicit `agents` section in effective config load path.
- [x] Validate allowed keys and reject unknown agent keys.
- [x] Enforce at least one enabled agent.
- [x] Return precise, actionable validation errors referencing `config.yml` paths.
- [x] Update config spec docs to match enforced contract.

### Files (expected)

- `teleclaude/config/__init__.py`
- `teleclaude/config/schema.py`
- `docs/project/spec/teleclaude-config.md`

## Phase 2 — Central Agent Policy Surface

- [ ] Add/standardize canonical known-agent constant(s) in one module.
- [ ] Add helper APIs:
  - [ ] `get_known_agents()`
  - [ ] `get_enabled_agents()`
  - [ ] `is_agent_enabled(name)`
  - [ ] rejection helper for disabled agent selection
- [ ] Ensure helpers are import-safe and reusable across core/API/TUI/MCP.

### Files (expected)

- `teleclaude/core/agents.py`
- `teleclaude/constants.py` (if needed for canonical IDs)

## Phase 3 — Enforce in Dispatch/Start Paths

- [ ] Enforce enabled-agent policy before start/resume/restart and worker dispatch.
- [ ] Reject disabled selection in:
  - [ ] API session creation path
  - [ ] MCP `teleclaude__start_session`
  - [ ] MCP `teleclaude__run_agent_command`
  - [ ] core command handlers (`start_agent`, `resume_agent`, `agent_restart`)
- [ ] Ensure fallback picker logic uses enabled-agent helper.

### Files (expected)

- `teleclaude/api_server.py`
- `teleclaude/mcp/handlers.py`
- `teleclaude/mcp_server.py` (if direct tool entry paths bypass handler-level checks)
- `teleclaude/core/command_handlers.py`
- `teleclaude/helpers/agent_cli.py`

## Phase 4 — Next-Machine Guidance and UX Behavior

- [ ] Replace blank guidance content with explicit placeholders when strengths/avoid are unset.
- [ ] Ensure next-machine guidance lists only enabled+available agents.
- [ ] TUI agent lists and selectors derive from policy helpers (no fixed lists for selection logic).
- [ ] Add explicit blocking feedback for zero-enabled configuration.

### Files (expected)

- `teleclaude/core/next_machine/core.py`
- `teleclaude/cli/tui/widgets/modal.py`
- `teleclaude/cli/tui/widgets/footer.py`
- `teleclaude/cli/tui/widgets/status_bar.py`
- `teleclaude/api_server.py`

## Phase 5 — Tests

- [ ] Config validation tests for missing `agents`, all-disabled, unknown keys.
- [ ] Unit tests for centralized helper behavior.
- [ ] API/MCP path tests for disabled-agent rejection.
- [ ] Next-machine guidance tests for non-blank output semantics.
- [ ] TUI/tests for selectable agent behavior from policy-driven source.

### Files (expected)

- `tests/unit/test_agent_guidance.py`
- `tests/unit/...` config tests
- `tests/unit/...` command/API/MCP tests
- TUI-related tests where applicable

## Rollout Notes

- Keep error messages stable and explicit to reduce operator confusion.
- Prefer incremental refactor: establish helper surface first, then migrate call sites.
- Do not change provider/model behavior; only selection/enforcement contract.

## Verification Plan

- [ ] `uv run pytest -q tests/unit/test_agent_config_loading.py tests/unit/test_config.py tests/unit/test_config_schema.py`
- [ ] `uv run pytest -q tests/unit/test_agent_guidance.py tests/unit/test_agent_cli.py tests/unit/test_agents.py`
- [ ] `uv run pytest -q tests/unit/test_mcp_handlers.py tests/unit/test_mcp_server.py tests/unit/test_command_handlers.py tests/unit/test_api_server.py`
- [ ] `uv run pytest -q tests/unit/test_tui_modal.py tests/unit/test_tui_agent_status.py`
- [ ] `uv run pytest -q tests/integration/test_mcp_tools.py tests/integration/test_run_agent_command_e2e.py`

## Definition of Done

- [ ] Config fails closed when agent policy is invalid.
- [ ] All dispatch/select surfaces use centralized enabled-agent policy.
- [ ] No blank agent-guidance lines.
- [ ] Tests cover fail-closed contract and pass in CI.
