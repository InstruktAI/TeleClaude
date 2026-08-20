---
description: DeepSeek Harness (dsh) as a first-class agent runtime — registry entry launched as the interactive TUI profile (`dsh --profile tui`), CC-compatible hook adapter, installer wiring of receiver hooks, and package-owned dsh-hooks activation.
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
`deepseek`, launched as the interactive TUI profile (`dsh --profile dsh-tui`)
in the session pane; the daemon waits for TUI readiness and types the prompt,
like claude. Sessions persist under `~/.dsh/sessions` as zstd-compressed
JSONL transcripts. Hooks flow back into
TeleClaude through the unified receiver: the `deepseek` adapter
(`teleclaude/hooks/adapters/dsh.py`) normalizes the Claude Code-shaped stdin
payloads emitted by the dsh-hooks plugin, which fires on session, turn, prompt,
and tool events. The dsh-hooks plugin is authored at
`$DSH_HOME/plugins/dsh-hooks` per the DSH plugin-authoring convention and is
never imported into this repository; this repository carries only the
installer wiring in `bin/install.sh`.

Wiring is installer-owned and idempotent: `bin/install.sh` installs the CLI
via npm, installs the plugin package into the `tui` (agent), `web`, and
`headless` profiles (the `tui` profile itself is user-managed), and
`configure_agent_cli` builds the receiver map and delegates to `configure_dsh`
(`teleclaude/install/dsh_hooks_install.py`), which writes the global
`~/.dsh/hooks.json` (nested Claude Code settings shape, receiver commands with
the explicit `unsandboxed: true` opt-in). Plugin activation remains package-owned:
`dsh plugin --profile <name> add` retains the package's declared
`dsh.bundle.patch`, so each installed profile composes the plugin's own
`cordis.patch.yml`. TeleClaude never writes a global activation row and never
strips the installed bundle entry.

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

#### UC-DSH-PATCH-1 (r2): the installed package owns plugin activation

Supersedes UC-DSH-PATCH-1 (r1): activation no longer rides a TeleClaude-authored
machine patch; the installed package's declared bundle patch is the authority.

```
Given an existing DSH profile
And the dsh-hooks package declares dsh.bundle.patch as ./cordis.patch.yml
When setup_dsh_integration installs the package into that profile
Then the profile retains its dsh-hooks dependency and bundle entry
And the profile composes the package-owned cordis.patch.yml at boot
And TeleClaude does not write a dsh-hooks row into ~/.dsh/cordis.patch.yml
```

#### UC-DSH-INSTALL-1 (r4): installer provisions the runtime end to end

Supersedes UC-DSH-INSTALL-1 (r3): installed profiles retain the dsh-hooks
package bundle so its own patch activates the plugin; TeleClaude configures
receiver hooks without authoring a separate activation layer.

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
And each installed profile retains the package-owned dsh-hooks bundle entry
And configure_agent_cli has written only the global receiver hooks config
```

#### UC-DSH-INSTALL-2: missing plugin source is non-fatal

```
Given setup_dsh_integration runs with no plugin package at $DSH_HOME/plugins/dsh-hooks
When it completes
Then a warning names the missing path and the provisioning step
And the install continues without aborting
```

#### UC-DSH-INSTALL-3 (r5): the plugin pass installs the local checkout into every profile

Supersedes UC-DSH-INSTALL-3 (r4): the pass covers every profile the operator
keeps, and every plugin package in the DSH plugins checkout is installed from
there — the checkout is the authoritative source for the plugins it holds, so a
locally restored build is never overwritten by its published counterpart.

```
Given dsh is installed
And $DSH_HOME/plugins holds one directory per locally maintained plugin
And $DSH_HOME/profiles holds one directory per profile
When setup_dsh_integration completes
Then dsh_install_plugins_all_profiles.sh has run
And the script is symlinked to $DSH_HOME/install-plugins.sh for manual re-runs
And every profile directory carrying a package.json received every plugin
  package under $DSH_HOME/plugins as a file: reference, plus the third-party
  dsh-checkpoint-rewind from the registry
And no profile was created; $DSH_HOME/profiles/node_modules is not a profile
And a failure of the plugins script warns and does not abort the install
```

#### UC-DSH-INSTALL-4 (r2): the operator adds extra plugins

Supersedes UC-DSH-INSTALL-4 (r1): extras are comma-separated and add to the
plugin set rather than replacing it.

```
Given the operator runs $DSH_HOME/install-plugins.sh
When plugins are passed as a comma-separated argument
Then each is added to every profile after the built-in set, for that run
When $DSH_HOME/extra-plugins holds a comma-separated or one-per-line list
Then each entry is added on every run, '#' starting a comment line
And surrounding whitespace is trimmed from every entry
```

#### UC-DSH-INSTALL-5: an unusable profile does not withhold plugins from the rest

```
Given one profile cannot be installed into (for example its node_modules are
  linked to a pnpm store that has moved)
When the plugin pass reaches it
Then that profile is reported and skipped
And every remaining profile still receives the full plugin set
And the pass exits non-zero, so setup_dsh_integration warns that it failed
```

<!-- planned:agent-vocabulary-single-registry -->

#### UC-DSH-AUTH-1: runner setup checks DeepSeek authentication

```gherkin
Given DeepSeek is enabled as an agent runtime
When an agent or operator runs the managed-runner setup preflight
Then the DeepSeek CLI authentication state is checked with the other enabled runtimes
And an unusable authentication state is surfaced before managed work is dispatched to DeepSeek
```

<!-- /planned:agent-vocabulary-single-registry -->

### macOS launcher

`DeepSeekLauncher.app` is built by `make launchers` (`src/Launcher/build.sh`,
target `deepseek`: executable `dsh`, override env `DSH_PATH`, passthrough
argv) and installed to `~/Applications` by `install_launchers`. On macOS,
`resolve_agent_binary("deepseek")` resolves to the launcher binary; the
launch command `dsh --profile dsh-tui <prompt>` is passed through as argv.
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
And the turn's tool calls are extracted (pre_tool_use/tool_result from
  assistant/message and tool/call, tool/result events)
And turn-local file changes are attributed to the session's workspace
And a checkpoint reason is emitted as {"decision": "block", "reason": ...}
  on the Stop hook's stdout
And the dsh-hooks plugin keeps the turn going with the reason injected
```

#### UC-DSH-CHECKPOINT-2: unmapped DSH stops mint a headless mapping instead of dropping

```
Given a deepseek session whose hooks fire from a tmux whose contract
  belongs to another agent (or from no TeleClaude tmux at all)
And the session has no TeleClaude session row and no cached mapping
When the receiver resolves a Stop (or SessionStart) hook event
Then the tmux-contract mismatch is never attributed to the marker session
And the event falls through to the shared resolution path
And the adapter-declared mint set (session_start, agent_stop) mints a
  headless session id instead of dropping the event
And the outbox dispatcher creates the headless session row (launch intent
  carries the default thinking mode med when the payload carries none)
And every adapter mints agent_stop (claude, gemini, codex, deepseek), so
  unmapped stops uniformly become headless sessions rather than drops
```

#### UC-DSH-DISTRIBUTE-1: artifact expansion renders and deploys the DSH master

```
Given the mother project's agents/ directory carries DEEPSEEK.addendum.md
And ~/.dsh exists on the machine
When the artifact expansion routine runs with agents enabled
Then the deepseek agent is processed like claude/codex/gemini
And a dist/deepseek/AGENTS.md master is rendered from the global masters,
  inline-expanded, and appended with the DEEPSEEK.addendum.md failure modes
And the deploy writes ~/.dsh/AGENTS.md (plus agents/commands/skills
  subdirs when artifact items exist, mirroring the other agents)
And skills transform through the deepseek SKILL.md shape (plain frontmatter)
And a machine without ~/.dsh skips deepseek like the other agents
```

#### UC-DSH-SEARCH-1: history search indexes DSH sessions

```
Given deepseek sessions persist under ~/.dsh/sessions as session.jsonl.zstd
When the mirror worker reconciles transcripts (or telec history search runs)
Then DSH transcripts are discovered under the deepseek session root
And a delegated child session — whose session entry carries parentSession —
  yields no session id and is skipped, as Claude's agent- subagent
  transcripts are
And each remaining transcript's native session id is read from its session
  entry (a legacy session- prefix is normalized; the parent directory name
  is the fallback when the entry is unreadable)
And the project is recovered from the session entry's cwd
And a conversation mirror is generated and FTS-searchable
And `telec history search --agent deepseek <term>` returns matches
And `--agent all` includes deepseek sessions
```

#### UC-DSH-SCOPE-1: DSH transcripts feed scoping and transcript views

```
Given a deepseek session whose native transcript path is bound
When session scoping resolves paths for the session (checkpoint
  attribution, todo scaffolding)
Then the deepseek extractor returns write/edit and shell-mutator paths
  from the normalized tool timeline
And transcript rendering (parse_session_transcript and the
  AGENT_TRANSCRIPT_PARSERS registry) accepts the deepseek agent without
  an unknown-agent fallback
```

### Commit identity

`GIT_AUTHOR_IDENTITIES` maps `deepseek` to the identity
`deepseek <noreply@deepseek.co>`. The commit path resolves it as the deepseek
agent session's author identity.

### Boundaries

<!-- planned:agent-vocabulary-single-registry -->

- Structured schema-constrained one-shot calls are unsupported by the DeepSeek
runtime. The headless profile accepts task text and prints a final message,
but exposes no output-format, schema, response-field, or response-type
contract. The canonical agent definition records that capability as
unavailable, and structured one-shot callers receive an explicit unsupported-
capability refusal rather than an unknown-agent failure.
<!-- /planned:agent-vocabulary-single-registry -->

- The dsh-hooks plugin is not imported into this repository: it lives at
  `$DSH_HOME/plugins/dsh-hooks` (DSH authoring-location convention) and is
  installed per profile from there. Its package metadata owns the profile bundle
  patch and activation; TeleClaude owns only its receiver entries in the global
  hooks configuration. The repository's test moratorium therefore
  does not apply to it; its own verification is the live runtime path —
  `~/.dsh/logs/dsh-hooks/dsh-hooks.log`.
- No DSH profile is ever created by the installer: the plugin is installed
  only into profiles that already exist (`dsh plugin --profile X add`
  auto-initializes missing profiles, which the existence guard prevents).
  The per-profile dsh-hooks install targets `tui`, `web`, and `headless`; the
  plugin pass targets every existing profile. Both install from the machine
  authoring location, never from the registry: `$DSH_HOME/plugins` is a working
  checkout whose builds can be ahead of what is published, so a registry
  reference for a plugin kept there would silently replace the local build.
  Registry references are reserved for third-party plugins the machine does not
  hold, and for the operator's comma-separated extras.
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
  `session_pattern **/session.jsonl*` under `~/.dsh/sessions`, and session
  identity/project are read from the transcript's session entry (id, cwd),
  normalized across the `session-` prefix variants of older artifacts.
- Not every artifact under the session root is a session. DSH's session store
  mints `session-<n>` ordinals for delegated child sessions created without an
  explicit id and records the spawning session in `parentSession`; that field
  is the discriminator, and such a transcript carries no identity of its own.
  The `session-` prefix therefore does not imply a UUID follows it — the
  identity invariant stays a full UUID, and non-sessions are recognized before
  they reach it.
