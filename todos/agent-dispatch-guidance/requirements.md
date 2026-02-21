# Requirements: agent-dispatch-guidance

## Goal

Replace hardcoded agent selection matrices in the next-machine with config-driven guidance text that the orchestrator AI interprets. Agent availability and strengths are declared in `config.yml`. The next-machine composes a guidance block and embeds it in dispatch instructions. The orchestrator reads the work item and the guidance, then picks agent + thinking mode.

## Scope

### In scope:

- Add `agents` section to `config.yml` with `enabled`, `strengths`, `avoid` fields per agent
- Add `AgentDispatchConfig` schema to `teleclaude/config/schema.py`
- Wire config loading to read agent dispatch fields from `config.yml`
- Write `compose_agent_guidance()` function in next-machine
- Modify `format_tool_call()` to embed guidance instead of pre-selected agent/mode
- Delete `WORK_FALLBACK`, `PREPARE_FALLBACK`, `get_available_agent()`, `_pick_agent()`
- Update all call sites in `next_work()` and `next_prepare()`
- Update existing tests that mock the old selection machinery
- Update `agent_cli._pick_agent` to respect `config.agents.enabled`
- Update doc snippets (`teleclaude-config`, `next-machine`)

### Out of scope:

- `telec config agents` CLI subcommand (future work)
- Domain metadata on roadmap entries
- Changes to `mark_agent_status` MCP tool or DB availability layer
- Changes to `AGENT_PROTOCOL` or binary resolution

## Success Criteria

- [ ] `config.yml` has an `agents` section with `enabled`/`strengths`/`avoid` per agent
- [ ] No hardcoded fallback matrices remain in `core.py`
- [ ] `format_tool_call` output includes agent guidance block with placeholder values
- [ ] Disabled agents do not appear in guidance text
- [ ] Degraded agents are noted in guidance text with status
- [ ] All existing tests pass after migration
- [ ] New unit tests cover `compose_agent_guidance` and updated `format_tool_call`

## Constraints

- `config.yml` is the per-machine application config; `teleclaude.yml` is per-project runtime config
- Binary paths stay as constants in `AGENT_PROTOCOL` — not configurable
- Runtime degradation (rate limits) stays in DB via `mark_agent_status`
- Backwards compatible: missing `agents` section defaults to all enabled with empty strengths

## Risks

- Orchestrator AI might make poor agent choices without strong guidance text — mitigated by clear strengths/avoid descriptions
- Existing tests that mock `get_available_agent` will break — addressed in task 7
