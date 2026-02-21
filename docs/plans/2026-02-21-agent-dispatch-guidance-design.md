# Agent Dispatch Guidance — Design

## Problem

The next-machine uses hardcoded Python matrices (`WORK_FALLBACK`, `PREPARE_FALLBACK`) to select which agent runs each phase. This is:

- Rigid: no awareness of work item domain (frontend vs backend vs greenfield)
- Unmaintainable: adding preferences means editing Python dicts
- Wrong model: the orchestrator AI can infer domain from the work item — it should choose

## Solution

Replace deterministic agent selection with composed guidance text. The next-machine stops picking agents. Instead, it embeds a guidance block in the dispatch instructions. The orchestrator reads the work item, reads the guidance, and selects agent + thinking mode itself.

Agent availability and strengths are declared in `config.yml` (per-machine application config).

## Config Surface

`config.yml` gets an `agents` section:

```yaml
agents:
  claude:
    enabled: true
    strengths: 'architecture, oversight, review, preparation, general-purpose'
    avoid: 'frontend/UI coding, creative visual work'
  gemini:
    enabled: true
    strengths: 'frontend, UI, creative, greenfield, modern patterns'
    avoid: ''
  codex:
    enabled: true
    strengths: 'backend, thorough coverage, meticulous implementation'
    avoid: ''
```

Three fields per agent: `enabled`, `strengths`, `avoid`. All optional with sensible defaults (enabled=true, empty strings).

## Guidance Composition

A function `compose_agent_guidance(config, db)` that:

1. Filters `config.agents` to enabled agents
2. Checks DB for runtime degradation status
3. Composes text from `strengths`/`avoid` fields
4. Appends thinking mode guidance

Output example (all agents enabled, gemini degraded):

```
AGENT SELECTION — Choose agent and thinking_mode before dispatching.

Available agents:
- claude: architecture, oversight, review, preparation, general-purpose. Avoid: frontend/UI coding, creative visual work.
- gemini: frontend, UI, creative, greenfield, modern patterns. (degraded: rate_limited, until 14:30 UTC)
- codex: backend, thorough coverage, meticulous implementation.

Thinking mode:
- slow: complex/novel work, deep analysis, thorough review
- med: routine implementation, fixes, standard tasks
- fast: mechanical/clerical (finalize, defer, cleanup)

Assess the domain and complexity of this work item, then select agent and thinking_mode.
```

## Changes to format_tool_call

- Remove `agent` and `thinking_mode` parameters
- Add `guidance: str` parameter
- Template has `<your choice>` placeholders instead of pre-filled values
- Orchestrator fills them based on the guidance

## Deletions

From `core.py`:

- `PREPARE_FALLBACK`, `WORK_FALLBACK` dicts
- `get_available_agent()` function
- `_pick_agent()` inner function
- `format_agent_selection_error()`, `_extract_no_selectable_task_type()`
- `NO_SELECTABLE_AGENTS_PATTERN` regex
- All `selection = await _pick_agent(...)` call sites

From `config/__init__.py`:

- The `agents` block in `_validate_disallowed_runtime_keys` (allow it now)

## Additions

- `AgentDispatchConfig` in config schema: `enabled`, `strengths`, `avoid`
- `agents` field in config, loaded from `config.yml`
- `compose_agent_guidance()` in next-machine
- `AgentConfig.enabled` field, populated from config.yml

## Runtime Degradation

The `mark_agent_status` MCP tool and DB availability layer stay. They track runtime issues (rate limits, quota). The guidance composition checks both: config-enabled AND runtime status.

## Documentation

The `teleclaude-config` spec should clarify:

- `config.yml` = per-machine application config (computer, agents, services, remotes)
- `teleclaude.yml` = per-project runtime config (project name, jobs, business domains)
