---
description: DeepSeek Harness (dsh) as a first-class agent runtime — registry entry launched headless via `dsh --profile tuition`, CC-compatible hook adapter, installer wiring of receiver hooks and the machine-local cordis patch row, and the vendored dsh-hooks plugin.
visibility: public
---

# DeepSeek Harness Integration — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/spec/domain/config.md
- @docs/project/spec/feature/config/agents-inventory-requirement.md

## What it is

DeepSeek Harness (the `dsh` CLI) is a first-class agent runtime alongside
claude, gemini, and codex. It is registered in `AGENT_PROTOCOL` under the key
`deepseek`, launched headless via `dsh --profile tuition <prompt>` (one-shot
turn: the prompt is the positional launch argument — `prompt_at_launch: true`,
never typed into an interactive pane), and persists sessions under
`~/.dsh/sessions` as zstd-compressed JSONL transcripts. Hooks flow back into
TeleClaude through the unified receiver: the `deepseek` adapter
(`teleclaude/hooks/adapters/dsh.py`) normalizes the Claude Code-shaped stdin
payloads emitted by the vendored dsh-hooks plugin
(`teleclaude/hooks/dsh-hooks`, installed as `dsh-hooks`), which fires on
session, turn, prompt, and tool events.

Wiring is installer-owned and idempotent: `bin/install.sh` installs the CLI
via npm, bootstraps the `tuition` profile (base + headless app) plus the
plugin package into every profile, and `configure_dsh`
(`teleclaude/install/configure_agent_cli.py`) writes the global
`~/.dsh/hooks.json` (nested Claude Code settings shape, receiver commands with
the explicit `unsandboxed: true` opt-in) and merges the plugin row into the
machine-local `~/.dsh/cordis.patch.yml` so every profile activates it. The
per-profile bundle row is stripped — the loader rejects a duplicate entry id.

## Canonical fields

### Use cases

#### UC-DSH-AGENT-1: deepseek is a known, launchable agent

```
Given a config.yml whose agents section declares deepseek with enabled: true
And dsh is installed on PATH
When the config builder processes the merged config
Then agent-key validation accepts deepseek (known agent set)
And the agent registry holds a typed entry for deepseek
And get_agent_command("deepseek", thinking_mode="slow") == "dsh --profile tuition"
And get_agent_command("deepseek", native_session_id="abc") == "dsh --profile tuition --resume abc"
And the daemon launches the agent with the prompt as the positional argument
  (prompt_at_launch) and never types it into an interactive pane
```

#### UC-DSH-HOOKS-1: receiver hooks are configured globally and idempotently

```
Given configure_dsh runs on a machine with an existing ~/.dsh/hooks.json
When it completes
Then the hooks file is written in the nested CC settings shape with a $schema
And SessionStart/UserPromptSubmit/PreToolUse/PostToolUse/Stop/StopFailure
  receiver commands are present, each declaring unsandboxed: true
And pre-existing user hooks with different commands are preserved
And re-running configure_dsh does not duplicate receiver commands
```

#### UC-DSH-PATCH-1: machine-local patch row activates the plugin in every profile

```
Given configure_dsh runs on a machine whose ~/.dsh/cordis.patch.yml exists
When it completes
Then the file contains an insert row with id dsh-hooks
And pre-existing !!js expressions in the file are byte-preserved
And a profile boot resolves the plugin from its node_modules dependency
  (no per-profile bundle row; duplicate ids are rejected by the loader)
```

#### UC-DSH-INSTALL-1: installer provisions the runtime end to end

```
Given a fresh machine choosing DeepSeek Harness during setup_agents_interactive
When the installer completes
Then dsh is installed via npm (or reported as present)
And the tuition profile exists with the headless app bundle and the dsh-hooks
  dependency, and web/headless profiles carry the dependency
And configure_agent_cli has written the global hooks config and patch row
```

### Boundaries

- The dsh-hooks plugin is vendored in-repo (test moratorium: no unit tests;
  verification is the live runtime path — `~/.dsh/logs/dsh-hooks/dsh-hooks.log`).
- Hook commands run under the session sandbox by default; the receiver hooks
  declare the explicit `unsandboxed` opt-in because they write outside the
  workspace (state dir, outbox DB).
- DSH transcripts are zstd-compressed; session discovery uses
  `session_pattern **/session.jsonl*` under `~/.dsh/sessions`.
