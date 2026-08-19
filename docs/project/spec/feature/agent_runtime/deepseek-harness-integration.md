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

#### UC-DSH-AGENT-1 (r4): deepseek is a known, launchable agent

Supersedes UC-DSH-AGENT-1 (r3): the per-launch patch became fully ephemeral —
mode-chain `flags` are a parameter table rendered into a patch in the session
tmpdir, applied and discarded; the static restricted patch file was removed
and its sandbox override merged into the generated patch.

```
Given a config.yml whose agents section declares deepseek with enabled: true
And dsh is installed on PATH
When the daemon starts a session for the deepseek agent
Then agent-key validation accepts deepseek (known agent set)
And the session pane runs the dsh CLI with the tui profile
And the mode chain entry's `patch` (a JSON parameter map) is rendered
  into a patch file in the session's own tmpdir and passed via --patch
And the patch selects the mode's parameters (fast: deepseek-v4-flash;
  med: deepseek-v4-pro with high effort; slow: deepseek-v4-pro with max)
And the patch file is discarded with the session — no static patch files
  exist anywhere in the launch path
And the pane shows the TUI idle prompt before any message is typed
And the daemon types the user's prompt into the pane only after the TUI
  idle prompt appears
And a session resumed by its native id relaunches the CLI with the tui
  profile
And a restricted-profile launch merges a sandbox-policy override into the
  generated patch, confining the session to workspace-write (rooted at the
  session cwd)
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

#### UC-DSH-INSTALL-1 (r3): installer provisions the runtime end to end

Supersedes UC-DSH-INSTALL-1 (r2): the no-creation guard extends from the
tui profile to every target profile — the installer never creates any DSH
profile.

```
Given a fresh machine choosing DeepSeek Harness during setup_agents_interactive
And the dsh-hooks plugin package exists at $DSH_HOME/plugins/dsh-hooks
  (the installer precondition; provisioning it there is the operator's step —
  this repository never fetches or imports the plugin)
When the installer completes
Then dsh is installed via npm (or reported as present)
And no DSH profile was created by the installer
And the tui, web, and headless profiles carry the dsh-hooks dependency
  only when they already exist; each missing profile is reported and
  skipped, never created
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

dsh resolution does not depend on the pane PATH: the daemon pane PATH is a
best-effort capture of the user shell with a fallback to the launchd daemon
environment (which lacks npm's global bin), so the launcher bakes the
machine's npm global bin (`npm prefix -g` at build time) plus
`/opt/homebrew/bin` and `/usr/local/bin` as fixed candidates, before PATH.
Launch `--patch` overlays (mode parameters, restricted sandbox) flow through
the launcher's passthrough argv unchanged.

#### UC-DSH-CHECKPOINT-1: stop checkpoints evaluate the DSH transcript

```
Given a deepseek session whose turn executed file-touching tools
And a checkpoint is due for the session
When the receiver evaluates the Stop hook
Then the DSH session artifact (zstd JSONL) is decompressed and parsed
And the turn's tool calls are extracted (tool_use/tool_result from
  assistant/message and tool/call, tool/result events)
And turn-local file changes are attributed to the session's workspace
And a checkpoint reason is emitted as {"decision": "block", "reason": ...}
  on the Stop hook's stdout
And the dsh-hooks plugin keeps the turn going with the reason injected
```

### Commit identity

`GIT_AUTHOR_IDENTITIES` maps `deepseek` to the identity
`deepseek <noreply@deepseek.co>`. The commit path resolves it as the deepseek
agent session's author identity.

### Boundaries

- The dsh-hooks plugin is not imported into this repository: it lives at
  `$DSH_HOME/plugins/dsh-hooks` (DSH authoring-location convention) and is
  installed per profile from there. The repository's test moratorium therefore
  does not apply to it; its own verification is the live runtime path —
  `~/.dsh/logs/dsh-hooks/dsh-hooks.log`.
- No DSH profile is ever created by the installer: the plugin is installed
  only into profiles that already exist (`dsh plugin --profile X add`
  auto-initializes missing profiles, which the existence guard prevents).
- Launch parameters are per-launch patches, not CLI flags or static files:
  dsh has no model flag, so the mode chain entry's `patch` carries a JSON
  parameter map (loader-id -> config) that is rendered into a patch in the
  session's
  own tmpdir, applied via `--patch`, and discarded with the session. The
  agent-default-model entry is replace-semantics and must carry provider +
  model (model ids are the API's full ids, e.g. deepseek-v4-pro).
- Hook commands run under the session sandbox by default; the receiver hooks
  declare the explicit `unsandboxed` opt-in because they write outside the
  workspace (state dir, outbox DB). The opt-in is honored only for global-layer
  hooks.
- DSH transcripts are zstd-compressed; session discovery uses
  `session_pattern **/session.jsonl*` under `~/.dsh/sessions`.
