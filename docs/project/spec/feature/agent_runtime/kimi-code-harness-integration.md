---
description: Kimi Code (the `kimi` CLI) as an agent runtime — registry entry launched as an interactive TUI, composer-frame readiness, and session discovery over its per-agent JSONL wire logs.
visibility: internal
---

# Kimi Code Harness Integration — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/spec/feature/config/agents-inventory-requirement.md

## What it is

Kimi Code (the `kimi` CLI) is registered in `AGENT_PROTOCOL` under the key
`kimi`. It ships as a self-contained binary at a fixed path under its own home
rather than through a package manager, so it is never resolved from `PATH` and
needs no launcher bundle to hold a stable identity.

The session pane runs the interactive TUI; the daemon waits for the composer to
appear and types the prompt, as it does for claude and deepseek. Model
selection is a CLI flag whose value is the model alias declared in Kimi's own
configuration, so the mode chain carries flags rather than a launch overlay.

Sessions persist under the Kimi session root as uncompressed JSONL wire logs,
one per agent within a session, and a session directory is created on the
session's first message rather than at launch.

## Canonical fields

### Use cases

#### UC-KIMI-AGENT-1: kimi is a known, launchable agent

```
Given a config.yml whose agents section declares kimi with enabled: true
And the kimi binary exists at its fixed path under the Kimi home
When the daemon starts a session for the kimi agent
Then agent-key validation accepts kimi (known agent set)
And the session pane runs the kimi CLI with the fully autonomous flag
And the mode chain selects the model by alias (fast: the highspeed code
  alias; med: the code alias; slow: the flagship alias)
And a restricted-profile launch keeps the question channel and mounts the
  shared directories explicitly
And a session resumed by its native id relaunches the CLI with that id
```

#### UC-KIMI-READY-1: readiness matches the composer frame, never the menu cursor

```
Given a kimi session pane has been started
When the daemon evaluates pane readiness
Then the idle prompt is matched by the composer's frame edge followed by its
  ASCII prompt character
And the menu cursor glyph alone never satisfies readiness
And the workspace-trust gate rendered before any composer exists never
  satisfies readiness
And the daemon types the user's prompt only after the composer appears
```

#### UC-KIMI-SEARCH-1: discovery resolves kimi sessions and skips subagents

```
Given kimi sessions persist under the kimi session root as per-agent wire logs
When transcript discovery runs for the kimi agent
Then each session's native id is read from its session directory name with the
  directory prefix removed
And the project is recovered from the working directory recorded in the
  session's state file
And a wire log belonging to any agent other than the session's main agent
  yields no session id and is skipped
```

### Boundaries

- Kimi is resolved by absolute path on every platform. The binary lives at a
  fixed location under the Kimi home that survives reinstalls, which is the
  property the launcher bundles exist to provide for the package-manager CLIs.
- Reasoning effort is model configuration, not a launch parameter: Kimi's model
  entries declare their supported efforts and a default, and no CLI flag
  overrides them. A mode chain therefore varies by model alias alone.
- Every agent inside one Kimi session writes its own wire log beneath that
  session's directory. The session's main agent is the session; its siblings
  are subagents and carry no session identity.
