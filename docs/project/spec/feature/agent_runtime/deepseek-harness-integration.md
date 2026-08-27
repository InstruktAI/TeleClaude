---
description: DeepSeek Harness (dsh) as a first-class agent runtime — launch, checkpoint evaluation, transcript discovery, history indexing, and artifact distribution.
visibility: public
---

# DeepSeek Harness Integration — Spec
## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/spec/domain/config.md
- @docs/project/spec/feature/config/agents-inventory-requirement.md


## What it is

DeepSeek Harness (the `dsh` CLI) is a registered agent runtime alongside claude,
gemini, and codex. TeleClaude owns what it does with that runtime: launching a
session, evaluating stop checkpoints, discovering and identifying transcripts,
indexing them for history, and distributing agent artifacts to it.

The runtime's own surface — profiles, plugin management, launcher flags, the
headless one-shot contract, and the hook executor's compatibility limits — is
the vendor's, and is documented against the installed binary in
`third-party/deepseek-dsh/runtime-surface` and `third-party/deepseek-dsh/hooks`.
Provisioning steps belong to `project/procedure/onboard-agent-harness` and to
the installer itself.
## Canonical fields

### Use cases

#### UC-DSH-AGENT-1: deepseek is a known, launchable agent

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

On macOS `resolve_agent_binary("deepseek")` resolves to the signed
`DeepSeekLauncher.app` bundle rather than the bare binary, so the machine's
permission grants attach to a stable identity across rebuilds. Launch arguments
pass through the launcher unchanged. Bundle construction and signing are owned
by `software-development/procedure/macos-stable-code-signing`.
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
