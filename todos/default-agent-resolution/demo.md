# Demo: default-agent-resolution

## Validation

```bash
# 1. Config validation: daemon refuses to start without agents.default
python -c "
from teleclaude.config import load_config
import yaml, tempfile, os
# Write a config without agents.default
# Expected: ValueError mentioning 'agents.default'
"
```

```bash
# 2. Zero hardcoded "agent claude" in adapter/core code (outside tests, docs, enum def)
rg '"agent claude"' teleclaude/ --glob '!*test*' --glob '!*todo*' | grep -v 'AGENT_PROTOCOL\|AgentName\|# ' | wc -l
# Expected: 0
```

```bash
# 3. Zero enabled_agents[0] patterns
rg 'enabled_agents\[0\]' teleclaude/ | wc -l
# Expected: 0
```

```bash
# 4. Zero AgentName.CLAUDE used as default parameters
rg 'AgentName\.CLAUDE' teleclaude/ --glob '!*test*' | grep -E '=\s*AgentName\.CLAUDE' | wc -l
# Expected: 0
```

```bash
# 5. Tests pass
make test
```

```bash
# 6. Lint passes
make lint
```

## Guided Presentation

### Step 1: The single resolver

Open `teleclaude/core/agents.py` and show `get_default_agent()`. It reads from `config.default_agent` and validates the agent is enabled. No fallbacks, no hardcoded names.

### Step 2: Config-driven default

Show `config.yml` with the `agents.default: claude` field. Show that removing it or setting it to a disabled/unknown agent causes a parse-time `ValueError` with a clear message.

### Step 3: Call site audit

Run the grep commands from Validation steps 2-4. All return zero. Every adapter, hook, and API endpoint that needs a default agent calls `get_default_agent()`.

### Step 4: Discord launcher visibility

Show that `_post_or_update_launcher` now iterates over all managed forums (project forums + help_desk + all_sessions). Show that launcher threads are pinned to the top of their forums via `thread.edit(pinned=True)`.

### Step 5: Test coverage

Run `make test` and show the new tests: config validation (missing default, unknown agent, disabled agent), `get_default_agent()` happy path and error path.
