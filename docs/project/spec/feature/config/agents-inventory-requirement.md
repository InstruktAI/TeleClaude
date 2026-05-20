---
id: 'project/spec/feature/config/agents-inventory-requirement'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'config.yml:agents must declare a default agent that is known and enabled; agent keys must be in the known set; at least one agent must be enabled; runtime-only fields are rejected.'
---

# Agents Inventory Requirement — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

`config.yml` MUST declare an `agents` section describing which AI agents the
machine knows how to launch. v1 enforces a tight contract: the section is
required, every agent key must be one the runtime recognises (`claude`,
`gemini`, `codex` — derived from `teleclaude.constants:AGENT_PROTOCOL`), there
must be a `default` entry naming one of those known agents, the default must
be enabled, and at least one agent in total must be enabled. Binary paths and
`tmux_binary` are runtime policy — the user cannot configure them; declaring
them in `config.yml` is a hard error. The resulting `Config.agents` is a
dict of typed `AgentConfig` entries (one per AGENT_PROTOCOL key) populated
from the protocol definitions, with `enabled` toggled by the user's YAML.

## Canonical fields

### Use cases

#### UC-CFG-AGENTS-1: Valid agents block with explicit default

```
Given config.yml contains:
  agents:
    default: claude
    claude:
      enabled: true
    gemini:
      enabled: false
And no other agent keys are present
When _build_config runs over the merged config
Then _require_agents_section returns the agents mapping
And _validate_known_agent_keys passes (claude and gemini are in AGENT_PROTOCOL)
And default_agent is "claude" after lowercase normalization
And agents_registry contains an AgentConfig entry for every AGENT_PROTOCOL key
And claude.enabled is True, gemini.enabled is False
And codex.enabled is True (default when user omits the key)
And Config.default_agent == "claude"
```

#### UC-CFG-AGENTS-2: Missing agents section is rejected

```
Given config.yml omits the top-level `agents:` key entirely
When _require_agents_section runs
Then ValueError is raised with the message:
  "Missing required config key `config.yml:agents`. Add `agents:` with at least one configured agent entry."
And _build_config does not reach agent registry construction
```

#### UC-CFG-AGENTS-3: agents value of wrong shape is rejected

```
Given config.yml contains `agents: [claude, gemini]` (a list, not a mapping)
When _require_agents_section runs
Then ValueError is raised with the message:
  "Invalid config key `config.yml:agents`: expected a mapping of agent names to settings."
```

#### UC-CFG-AGENTS-4: Missing default is rejected

```
Given config.yml contains an agents block with `claude:` and `gemini:` entries but no `default:` key
When _build_config processes the agents mapping
Then default_agent_raw is None
And ValueError is raised including the text:
  "Missing required config key `config.yml:agents.default`."
And the message lists the allowed agents (claude, gemini, codex)
```

#### UC-CFG-AGENTS-5: Default naming an unknown agent is rejected

```
Given config.yml contains `agents.default: groq` (not in AGENT_PROTOCOL)
When _build_config processes the agents mapping
Then ValueError is raised including the text:
  "Invalid config key `config.yml:agents.default`: unknown agent 'groq'."
And the message lists the allowed values
```

#### UC-CFG-AGENTS-6: Default value of non-string type is rejected

```
Given config.yml contains `agents.default: 42` (a non-string)
When _build_config processes the agents mapping
Then ValueError is raised including:
  "Invalid config key `config.yml:agents.default`: expected a string"
```

#### UC-CFG-AGENTS-7: Unknown agent keys are rejected

```
Given config.yml contains an `agents.gpt5` block alongside known keys
When _validate_known_agent_keys runs
Then ValueError is raised with:
  "Unknown key(s) under `config.yml:agents`: gpt5. Allowed keys: claude, gemini, codex."
And the unknown keys list is sorted alphabetically
```

#### UC-CFG-AGENTS-8: All-agents-disabled is rejected

```
Given config.yml contains agents.default: claude
And every known agent has `enabled: false`
When _build_config builds the agents_registry
Then ValueError is raised with:
  "Invalid config at `config.yml:agents`: all known agents are disabled."
```

#### UC-CFG-AGENTS-9: Default agent disabled is rejected

```
Given config.yml contains:
  agents:
    default: claude
    claude: { enabled: false }
    gemini: { enabled: true }
When _build_config checks agents_registry[default_agent].enabled
Then ValueError is raised with:
  "Invalid config key `config.yml:agents.default`: 'claude' is disabled."
```

#### UC-CFG-AGENTS-10: Disallowed runtime key computer.tmux_binary is rejected

```
Given config.yml contains:
  computer:
    tmux_binary: /usr/local/bin/tmux
When _validate_disallowed_runtime_keys runs over the user config
Then ValueError is raised with:
  "config.yml contains disallowed runtime keys: computer.tmux_binary. Agent and tmux binaries are now hardcoded runtime policy and cannot be configured."
And _build_config is never reached
```

#### UC-CFG-AGENTS-11: Per-agent binary is filled from runtime policy

```
Given a valid agents block accepts at _build_config
When agents_registry is built
Then for each name in AGENT_PROTOCOL.keys() an AgentConfig is constructed
And AgentConfig.binary is set by resolve_agent_binary(name) (platform-resolved)
And ComputerConfig.tmux_binary is set by resolve_tmux_binary()
And the user has no surface to override these binary paths
```

### Implementation pointers (v1)

- `teleclaude/constants.py:473+` — `AGENT_PROTOCOL` mapping (known agent keys: `claude`, `gemini`, `codex`); per-agent profiles, session paths, flags, templates.
- `teleclaude/config/__init__.py:495-509` — `_validate_disallowed_runtime_keys` (rejects `computer.tmux_binary`).
- `teleclaude/config/__init__.py:512-521` — `_require_agents_section` (presence + mapping shape).
- `teleclaude/config/__init__.py:524-533` — `_validate_known_agent_keys` (unknown-key rejection with sorted list).
- `teleclaude/config/__init__.py:706-744` — default-agent extraction and validation (`pop("default")`, presence, type, membership in `AGENT_PROTOCOL`).
- `teleclaude/config/__init__.py:746-768` — agents_registry construction: every `AGENT_PROTOCOL` key gets an `AgentConfig`; user can only flip `enabled`.
- `teleclaude/config/__init__.py:770-779` — "all disabled" and "default disabled" rejection.
- `teleclaude/runtime/binaries.py:30-48` — `resolve_tmux_binary()` and `resolve_agent_binary(name)` runtime resolution (macOS uses Application bundles; other platforms use bare command names).

### Cross-context references

- v1 does NOT emit `config.effective.updated` (or any config event) when this
  validation fires or the agents inventory changes. Validation failures
  surface as `ValueError` raised during the import of `teleclaude.config`,
  i.e. at process start.
- Consumed by `agent_runtime` and any caller that spawns an agent: the
  resolved `Config.agents[<name>].binary` is the path used to launch the
  process; `Config.default_agent` is the fallback when the caller does not
  specify an agent.
- The v2 `config` bounded context (see `docs/project/spec/domain/config.md`)
  generalises this into a `RuntimeConfig` aggregate with the same
  invariants. The v1 contract — "default agent must be known and enabled,
  binaries are runtime policy" — survives the rewrite.

## Allowed values

- `agents.default`: one of `claude`, `gemini`, `codex` (the keys of
  `AGENT_PROTOCOL`). Case-insensitive; normalized via `strip().lower()`.
- `agents.<name>` where `<name>` ∈ {`claude`, `gemini`, `codex`}; any other
  key is rejected.
- `agents.<name>.enabled`: `true` or `false`. Defaults to `true` when the
  key is omitted from the user file for an `AGENT_PROTOCOL` agent.
- `computer.tmux_binary`: forbidden. Resolution is platform-derived.

## Known caveats

- **Unlisted agents default to enabled.** `agents_registry` iterates every
  `AGENT_PROTOCOL` key (line 749). A user who only declares `claude` still
  gets `gemini` and `codex` with `enabled=True`, because the default in
  `user_agent_config.get("enabled", True)` is `True`. To disable a known
  agent the user must declare it explicitly and set `enabled: false`.
- **`default` is popped from the agents mapping before key validation.**
  `_validate_known_agent_keys` sees the agents mapping with `default`
  already removed, so it does not need to special-case the literal string
  `"default"` in the unknown-key check.
- **Per-agent fields other than `enabled` are silently ignored.** The user
  may write `agents.claude.foo: bar`; `_build_config` only reads
  `enabled` from `user_agent_config`. The rest of the per-agent fields come
  from `AGENT_PROTOCOL`, not from the user file.
- **`_validate_disallowed_runtime_keys` only checks `computer.tmux_binary`.**
  Other historical runtime fields (e.g., per-agent `binary` overrides under
  `agents.<name>.binary`) are not actively rejected — they are silently
  dropped by being ignored at registry construction. The disallow list is
  scoped to the single known migration: `computer.tmux_binary`.
- **No length/min validation on the agents map.** A user could declare zero
  user-listed agents and still pass `_require_agents_section` (it only
  checks the section exists and is a mapping). The "at least one enabled"
  check is the practical floor — it fires later in `_build_config`.
- **Case folding affects `default` but not the other keys.** The default is
  normalised with `strip().lower()` (line 739); per-agent keys are matched
  case-sensitively against `AGENT_PROTOCOL` keys, so `Agents.CLAUDE: {…}`
  is rejected even though `agents.default: CLAUDE` is accepted.
