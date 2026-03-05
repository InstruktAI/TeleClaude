# Demo: transcript-parser-fallback-policy

## Validation

```bash
# Verify the centralized resolver exists and is importable
python -c "from teleclaude.core.agents import resolve_parser_agent; print('OK')"
```

```bash
# Verify fallback behavior returns Claude for unknown agents
python -c "
from teleclaude.core.agents import resolve_parser_agent, AgentName
assert resolve_parser_agent(None) == AgentName.CLAUDE
assert resolve_parser_agent('') == AgentName.CLAUDE
assert resolve_parser_agent('unknown_agent') == AgentName.CLAUDE
assert resolve_parser_agent('claude') == AgentName.CLAUDE
assert resolve_parser_agent('codex') == AgentName.CODEX
print('All assertions passed')
"
```

```bash
# Run the specific test file
python -m pytest tests/unit/test_agents.py -v -k "resolve_parser_agent"
```

## Guided Presentation

### Step 1: Show the centralized resolver

Open `teleclaude/core/agents.py` and locate `resolve_parser_agent()`. Observe:
- It handles `None`, empty string, known agents, and unknown agents.
- It logs at `debug` for `None`/empty (expected on fresh sessions) and `warning` for
  genuinely unknown values (indicates data quality issue or new agent type).

### Step 2: Show a callsite migration

Open `teleclaude/api/streaming.py` and show `_get_agent_name()`. Observe:
- The inline try/except and `or "claude"` default have been replaced with a single
  call to `resolve_parser_agent()`.
- Same simplification in `teleclaude/api_server.py`.

### Step 3: Run the tests

Run `python -m pytest tests/unit/test_agents.py -v -k resolve_parser_agent`. Observe:
- Canonical values resolve correctly.
- `None` and empty string resolve to Claude with debug-level log.
- Unknown values resolve to Claude with warning-level log.
- Case-insensitive matching works.
