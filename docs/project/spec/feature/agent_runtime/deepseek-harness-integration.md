---
description: DeepSeek Harness (dsh) as a first-class agent runtime — registry entry launched as the interactive TUI profile (`dsh --profile tui`), CC-compatible hook adapter, installer wiring of receiver hooks and the machine-local cordis patch row, and the dsh-hooks plugin authored at $DSH_HOME/plugins/dsh-hooks.
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
`deepseek`, launched as the interactive TUI profile (`dsh --profile tui`)
in the session pane; the daemon waits for TUI readiness and types the prompt,
like claude. Sessions persist under `~/.dsh/sessions` as zstd-compressed
JSONL transcripts. Hooks flow back into
TeleClaude through the unified receiver: the `deepseek` adapter
(`teleclaude/hooks/adapters/dsh.py`) normalizes the Claude Code-shaped stdin
payloads emitted by the dsh-hooks plugin, which fires on session, turn, prompt,
and tool events. The dsh-hooks plugin is authored at
`$DSH_HOME/plugins/dsh-hooks` per the DSH plugin-authoring convention and is
never imported into this repository; this repository carries only the
patch-row template (`templates/dsh-cordis.patch.yml`) and the installer
wiring in `bin/install.sh`.

Wiring is installer-owned and idempotent: `bin/install.sh` installs the CLI
via npm, installs the plugin package into the `tui` (agent), `web`, and
`headless` profiles (the `tui` profile itself is user-managed), and
`configure_dsh`
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
And get_agent_command("deepseek", thinking_mode="slow") == "dsh --profile tui"
And get_agent_command("deepseek", native_session_id="abc") == "dsh --profile tui --resume abc"
And the daemon launches `dsh --profile tui` in the session pane, waits for
  TUI readiness (the "> " prompt marker), and types the prompt into the pane
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
And the dsh-hooks plugin package exists at $DSH_HOME/plugins/dsh-hooks
  (the installer precondition; provisioning it there is the operator's step —
  this repository never fetches or imports the plugin)
When the installer completes
Then dsh is installed via npm (or reported as present)
And the tui, web, and headless profiles carry the dsh-hooks dependency
  (the tui profile is user-managed; the installer never creates one)
And configure_agent_cli has written the global hooks config and patch row
```

#### UC-DSH-INSTALL-2: missing plugin source is non-fatal

```
Given setup_dsh_integration runs with no plugin package at $DSH_HOME/plugins/dsh-hooks
When it completes
Then a warning names the missing path and the provisioning step
And the install continues without aborting
```

### macOS launcher

`DeepSeekLauncher.app` is built by `make launchers` (`src/Launcher/build.sh`,
target `deepseek`: executable `dsh`, override env `DSH_PATH`, passthrough
argv) and installed to `~/Applications` by `install_launchers`. On macOS,
`resolve_agent_binary("deepseek")` resolves to the launcher binary; the
launch command `dsh --profile tui <prompt>` is passed through as argv.
The signed bundle is the stable identity macOS TCC permissions attach to.

### Commit identity

`GIT_AUTHOR_IDENTITIES` maps `deepseek` to the identity
`deepseek <noreply@deepseek.co>`. The commit path resolves it as the deepseek
agent session's author identity; when a verified DeepSeek bot account exists,
the mapping is replaced by it.

### Boundaries

- The dsh-hooks plugin is not imported into this repository: it lives at
  `$DSH_HOME/plugins/dsh-hooks` (DSH authoring-location convention) and is
  installed per profile from there. The repository's test moratorium therefore
  does not apply to it; its own verification is the live runtime path —
  `~/.dsh/logs/dsh-hooks/dsh-hooks.log`.
- Hook commands run under the session sandbox by default; the receiver hooks
  declare the explicit `unsandboxed` opt-in because they write outside the
  workspace (state dir, outbox DB). The opt-in is honored only for global-layer
  hooks.
- DSH transcripts are zstd-compressed; session discovery uses
  `session_pattern **/session.jsonl*` under `~/.dsh/sessions`.
