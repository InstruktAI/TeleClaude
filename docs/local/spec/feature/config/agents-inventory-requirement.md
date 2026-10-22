---
description: Agent inventory validates a known enabled default, a nonempty enabled set and declared launch overrides while rejecting runtime-policy fields.
visibility: 'public'
---

# Agents Inventory Requirement — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

`config.yml` MUST declare an `agents` section describing which AI agents the
machine knows how to launch. v1 enforces a tight contract: the section is
required, every agent key must be one the runtime recognises (`claude`,
`gemini`, `codex`, `deepseek` — the platform's known agent keys), there
must be a `default` entry naming one of those known agents, the default must
be enabled, and at least one agent in total must be enabled. Binary paths and
`tmux_binary` are runtime policy — the user cannot configure them. Undeclared
runtime-policy fields are rejected by the machine config's closed section
models rather than by a bespoke disallow list. The resulting agent registry
holds a typed entry for each known agent key, populated from the protocol
definitions and then overlaid with the operator's YAML for exactly those
settings the `AgentConfig` field tiers declare as an operator surface.

Those tier markers are the single authority for that surface: a leaf marked
`public` or `tui` is operator-editable, every other leaf is runtime policy, and
exposing a new setting is a change to its marker rather than to the loader. A
setting the tiers do not expose is **rejected by name** at load, never accepted
and discarded — silent acceptance would let a config assert a launch contract
the runtime does not honor.

## Canonical fields

### Use cases

#### UC-CFG-AGENTS-1: Valid agents block with explicit default

#### UC-CFG-AGENTS-2: Missing agents section is rejected

#### UC-CFG-AGENTS-3: agents value of wrong shape is rejected

#### UC-CFG-AGENTS-4: Missing default is rejected

#### UC-CFG-AGENTS-5: Default naming an unknown agent is rejected

#### UC-CFG-AGENTS-6: Default value of non-string type is rejected

#### UC-CFG-AGENTS-7: Unknown agent keys are rejected

#### UC-CFG-AGENTS-8: All-agents-disabled is rejected

#### UC-CFG-AGENTS-9: Default agent disabled is rejected

#### UC-CFG-AGENTS-10: Undeclared runtime key computer.tmux_binary is rejected

#### UC-CFG-AGENTS-11: Per-agent binary is filled from runtime policy

### Cross-context references

- The config bounded context does not emit an effective-configuration-updated event
  for this validation today; validation failures surface as load-time errors
  at process start and are not propagated as a config event. Generalising
  this signal into the effective-configuration event taxonomy is described
  in `local/projects/teleclaude/spec/domain/config.md`.
- Consumed by the `agent_runtime` context and any caller that spawns an
  agent: the resolved agent binary is what launches the process, and the
  enabled inventory constrains fresh-session eligibility. The declared default remains
  a required configuration invariant but does not resolve an omitted fresh-session
  agent; role-aware dispatch owns that choice.
- The `config` bounded context (`local/projects/teleclaude/spec/domain/config.md`) carries
  the same invariants — "default agent must be known and enabled, binaries
  are runtime policy" — at the domain level.

## Allowed values

- `agents.default`: one of `claude`, `gemini`, `codex`, `deepseek` (the known agent keys).
  Case-insensitive; normalized by trimming and lowercasing.
- `agents.<name>` where `<name>` ∈ {`claude`, `gemini`, `codex`, `deepseek`}; any
  other key is rejected.

- `agents.<name>.enabled`: `true` or `false`. Defaults to `true` when the
  key is omitted from the user file for a known agent.

- `computer.tmux_binary`: undeclared and rejected by the closed `computer`
  input shape. Resolution is platform-derived.

## Known caveats

- **Unlisted agents default to enabled.** The agent registry iterates every
  known agent key. A user who only declares `claude` still gets `gemini` and
  `codex` with `enabled=True`, because the default for an unlisted agent's `enabled` field is `True`.
  To disable a known agent the user must declare it explicitly and set `enabled: false`.

- **`default` is popped from the agents mapping before key validation.**
  Agent-key validation sees the agents mapping with `default` already removed,
  so it does not need to special-case the literal string `"default"` in the
  unknown-key check.
- **Only tier-declared per-agent settings are accepted.** At the current
  schema, `enabled` is TUI-editable and `profiles` and `model_chains` are
  public configuration fields. Any other per-agent field is refused by name
  by the closed settings validator; it is never accepted and discarded.
  Platform-derived values such as `binary` remain runtime policy.
- **Runtime-policy fields are outside the accepted input shape.** Historical
  runtime fields such as `computer.tmux_binary` and per-agent `binary`
  overrides are rejected as undeclared keys rather than accepted and dropped.

- **No length/min validation on the agents map.** A user could declare zero
  user-listed agents and still pass the agents-section check (it only
  checks the section exists and is a mapping). The "at least one enabled"
  check is the practical floor — it fires later in config construction.

- **Case folding affects `default` but not the other keys.** The default is
  normalised by trimming and lowercasing; per-agent keys are matched
  case-sensitively against the known agent keys, so `Agents.CLAUDE: {…}`
  is rejected even though `agents.default: CLAUDE` is accepted.
