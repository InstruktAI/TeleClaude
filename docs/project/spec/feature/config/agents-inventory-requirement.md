---
description: 'The machine config `agents` section must declare a default agent that is known and enabled; agent keys must be in the known set; at least one agent must be enabled; runtime-only fields are rejected.'
visibility: 'public'
---

# Agents Inventory Requirement — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

<!-- planned-change:config-schema-strictness -->
`config.yml` MUST declare an `agents` section describing which AI agents the
machine knows how to launch. v1 enforces a tight contract: the section is
required, every agent key must be one the runtime recognises (`claude`,
`gemini`, `codex`, `deepseek` — the platform's known agent keys), there
must be a `default` entry naming one of those known agents, the default must
be enabled, and at least one agent in total must be enabled. Binary paths and
`tmux_binary` are runtime policy — the user cannot configure them; declaring
them in `config.yml` is a hard error. The resulting agent registry holds a
typed entry for each known agent key, populated from the protocol definitions
and then overlaid with the operator's YAML for exactly those settings the
`AgentConfig` field tiers declare as an operator surface.
<!-- change:config-schema-strictness -->
`config.yml` MUST declare an `agents` section describing which AI agents the
machine knows how to launch. v1 enforces a tight contract: the section is
required, every agent key must be one the runtime recognises (`claude`,
`gemini`, `codex`, `deepseek` — the platform's known agent keys), there
must be a `default` entry naming one of those known agents, the default must
be enabled, and at least one agent in total must be enabled. Binary paths and
`tmux_binary` are runtime policy — the user cannot configure them. Undeclared
runtime-policy fields are rejected by the machine config's parser-owned input
shape rather than by a bespoke disallow list. The resulting agent registry
holds a typed entry for each known agent key, populated from the protocol
definitions and then overlaid with the operator's YAML for exactly those
settings the `AgentConfig` field tiers declare as an operator surface.
<!-- /planned-change:config-schema-strictness -->

Those tier markers are the single authority for that surface: a leaf marked
`public` or `tui` is operator-editable, every other leaf is runtime policy, and
exposing a new setting is a change to its marker rather than to the loader. A
setting the tiers do not expose is **rejected by name** at load, never accepted
and discarded — silent acceptance would let a config assert a launch contract
the runtime does not honor.

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
When the config builder processes the merged config
Then the agents-section check confirms the section is present
And agent-key validation passes (claude and gemini are in the known agent set)
And the default agent is "claude" after lowercase normalization
And the agent registry contains a typed entry for every known agent key
And claude.enabled is True, gemini.enabled is False
And codex.enabled is True (default when user omits the key)
And the resolved default_agent == "claude"
```

#### UC-CFG-AGENTS-2: Missing agents section is rejected

```
Given config.yml omits the top-level `agents:` key entirely
When the agents-section check runs
Then a validation error is raised with the message:
  "Missing required config key `config.yml:agents`. Add `agents:` with at least one configured agent entry."
And agent registry construction is never reached
```

#### UC-CFG-AGENTS-3: agents value of wrong shape is rejected

```
Given config.yml contains `agents: [claude, gemini]` (a list, not a mapping)
When the agents-section check runs
Then a validation error is raised with the message:
  "Invalid config key `config.yml:agents`: expected a mapping of agent names to settings."
```

#### UC-CFG-AGENTS-4: Missing default is rejected

```
Given config.yml contains an agents block with `claude:` and `gemini:` entries but no `default:` key
When the config builder processes the agents mapping
Then the default agent value is absent
And a validation error is raised including the text:
  "Missing required config key `config.yml:agents.default`."
And the message lists the allowed agents (claude, gemini, codex, deepseek)
```

#### UC-CFG-AGENTS-5: Default naming an unknown agent is rejected

```
Given config.yml contains `agents.default: groq` (not in the known agent set)
When the config builder processes the agents mapping
Then a validation error is raised including the text:
  "Invalid config key `config.yml:agents.default`: unknown agent 'groq'."
And the message lists the allowed values
```

#### UC-CFG-AGENTS-6: Default value of non-string type is rejected

```
Given config.yml contains `agents.default: 42` (a non-string)
When the config builder processes the agents mapping
Then a validation error is raised including:
  "Invalid config key `config.yml:agents.default`: expected a string"
```

#### UC-CFG-AGENTS-7: Unknown agent keys are rejected

```
Given config.yml contains an `agents.gpt5` block alongside known keys
When agent-key validation runs
Then a validation error is raised with:
  "Unknown key(s) under `config.yml:agents`: gpt5. Allowed keys: claude, gemini, codex, deepseek."
And the unknown keys list is sorted alphabetically
```

#### UC-CFG-AGENTS-8: All-agents-disabled is rejected

```
Given config.yml contains agents.default: claude
And every known agent has `enabled: false`
When the config builder builds the agent registry
Then a validation error is raised with:
  "Invalid config at `config.yml:agents`: all known agents are disabled."
```

#### UC-CFG-AGENTS-9: Default agent disabled is rejected

```
Given config.yml contains:
  agents:
    default: claude
    claude: { enabled: false }
    gemini: { enabled: true }
When the config builder checks whether the default agent is enabled
Then a validation error is raised with:
  "Invalid config key `config.yml:agents.default`: 'claude' is disabled."
```

<!-- planned-change:config-schema-strictness -->
#### UC-CFG-AGENTS-10: Disallowed runtime key computer.tmux_binary is rejected

```
Given config.yml contains:
  computer:
    tmux_binary: /usr/local/bin/tmux
When the disallowed-key check runs over the user config
Then a validation error is raised with:
  "config.yml contains disallowed runtime keys: computer.tmux_binary. Agent and tmux binaries are now hardcoded runtime policy and cannot be configured."
And config construction is never reached
```
<!-- change:config-schema-strictness -->
#### UC-CFG-AGENTS-10: Undeclared runtime key computer.tmux_binary is rejected

```
Given config.yml contains:
  computer:
    tmux_binary: /usr/local/bin/tmux
When the machine config validates raw operator input
Then validation rejects `computer.tmux_binary` as an unknown key
And config construction is never reached
```
<!-- /planned-change:config-schema-strictness -->

#### UC-CFG-AGENTS-11: Per-agent binary is filled from runtime policy

```
Given a valid agents block reaches the agent registry build step
When the agent registry is built
Then for each known agent key a typed entry is constructed
And each entry's binary path is resolved by the platform (not user-configurable)
And the tmux binary is likewise resolved by the platform
And the user has no surface to override these binary paths
```

### Cross-context references

- The config bounded context does not emit a `config.effective.updated` event
  for this validation today; validation failures surface as load-time errors
  at process start and are not propagated as a config event. Generalising
  this signal into the effective-configuration event taxonomy is described
  in `project/spec/domain/config.md`.
- Consumed by the `agent_runtime` context and any caller that spawns an
  agent: the resolved agent binary is what launches the process, and the
  enabled inventory constrains fresh-session eligibility. The declared default remains
  a required configuration invariant but does not resolve an omitted fresh-session
  agent; role-aware dispatch owns that choice.
- The `config` bounded context (`project/spec/domain/config.md`) carries
  the same invariants — "default agent must be known and enabled, binaries
  are runtime policy" — at the domain level.

## Allowed values

- `agents.default`: one of `claude`, `gemini`, `codex`, `deepseek` (the known agent keys).
  Case-insensitive; normalized by trimming and lowercasing.
- `agents.<name>` where `<name>` ∈ {`claude`, `gemini`, `codex`, `deepseek`}; any
  other key is rejected.
- `agents.<name>.enabled`: `true` or `false`. Defaults to `true` when the
  key is omitted from the user file for a known agent.
<!-- planned-change:config-schema-strictness -->
- `computer.tmux_binary`: forbidden. Resolution is platform-derived.
<!-- change:config-schema-strictness -->
- `computer.tmux_binary`: undeclared and rejected by the closed `computer`
  input shape. Resolution is platform-derived.
<!-- /planned-change:config-schema-strictness -->

## Known caveats

- **Unlisted agents default to enabled.** The agent registry iterates every
  known agent key. A user who only declares `claude` still gets `gemini` and
  `codex` with `enabled=True`, because the default for an unlisted agent's `enabled` field is `True`.
  To disable a known agent the user must declare it explicitly and set `enabled: false`.
- **`default` is popped from the agents mapping before key validation.**
  Agent-key validation sees the agents mapping with `default` already removed,
  so it does not need to special-case the literal string `"default"` in the
  unknown-key check.
- **Per-agent fields other than `enabled` are silently ignored.** The user
  may write `agents.claude.foo: bar`; the config builder only reads `enabled`
  from the per-agent config. The rest of the per-agent fields come from the
  protocol definitions, not from the user file.
<!-- planned-change:config-schema-strictness -->
- **The disallowed-key check only validates `computer.tmux_binary`.**
  Other historical runtime fields (e.g., per-agent `binary` overrides under
  `agents.<name>.binary`) are not actively rejected — they are silently
  dropped by being ignored at registry construction. The disallow list is
  scoped to the single known migration: `computer.tmux_binary`.
<!-- change:config-schema-strictness -->
- **Runtime-policy fields are outside the accepted input shape.** Historical
  runtime fields such as `computer.tmux_binary` and per-agent `binary`
  overrides are rejected as undeclared keys rather than accepted and dropped.
<!-- /planned-change:config-schema-strictness -->
- **No length/min validation on the agents map.** A user could declare zero
  user-listed agents and still pass the agents-section check (it only
  checks the section exists and is a mapping). The "at least one enabled"
  check is the practical floor — it fires later in config construction.
- **Case folding affects `default` but not the other keys.** The default is
  normalised by trimming and lowercasing; per-agent keys are matched
  case-sensitively against the known agent keys, so `Agents.CLAUDE: {…}`
  is rejected even though `agents.default: CLAUDE` is accepted.
