# Requirements: default-agent-resolution

## Goal

Eliminate all hardcoded agent names and fragile index-based agent selection. Establish a single, config-driven, fail-fast resolver as the sole source of truth for default agent resolution. Fix Discord launcher visibility.

## Scope

### In scope:
- Add `default_agent` field to config schema with parse-time validation
- Create `get_default_agent()` in `core/agents.py` — single resolver, no fallbacks
- Replace all 14 call sites that resolve a default agent (see implementation plan for full inventory)
- Delete redundant helpers: `_default_agent` property, `_default_agent_name()` function
- Pin Discord launcher threads to forum top via `thread.edit(pinned=True)`
- Post launchers to all managed forums (help_desk, all_sessions, project forums)

### Out of scope:
- Person-level agent preference (YAGNI — no second consumer today)
- Fixing the bootstrap silent failure paths (separate bug investigation)
- Changing how explicit user selection works (launcher buttons, TUI modal — already correct)

## Success Criteria

- [ ] `config.yml` requires `agents.default` — daemon refuses to start without it
- [ ] `get_default_agent()` is the only function that resolves a default agent name
- [ ] Zero hardcoded `"claude"` / `"gemini"` / `"codex"` strings in adapter code or command mapper
- [ ] Zero `enabled_agents[0]` patterns anywhere in codebase
- [ ] `AgentName.CLAUDE` not used as a default parameter in any function signature
- [ ] Launcher threads appear pinned (sticky) at the top of every managed Discord forum
- [ ] Launchers posted to help_desk and all_sessions forums, not just project forums
- [ ] All existing tests pass; new tests cover config validation and resolver
- [ ] `make lint` passes

## Constraints

- Adapter boundary policy: adapters must not contain agent resolution logic — they call core
- Fail-fast policy: missing or invalid config raises at parse time, not at first use
- No fallbacks, no silent defaults, no defensive `if/else` chains
- Config change is backward-incompatible: existing configs without `agents.default` will fail validation (this is intentional — force explicit declaration)

## Risks

- Existing deployments without `agents.default` in config.yml will fail on daemon restart — mitigated by clear error message directing user to add the field
- Discord forum pin limit (1 pinned thread per forum) — the launcher is the only thread we'd pin, so this is fine
