---
description: DeepSeek Harness (dsh) as a first-class agent runtime — launch, checkpoint evaluation, transcript discovery, history indexing, and artifact distribution.
visibility: public
---

# DeepSeek Harness Integration — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md
- @docs/local/spec/domain/config.md
- @docs/local/spec/feature/config/agents-inventory-requirement.md

## What it is

DeepSeek Harness (the `dsh` CLI) is a registered agent runtime alongside claude,
gemini, and codex. TeleClaude owns what it does with that runtime: launching a
session, evaluating stop checkpoints, discovering and identifying transcripts,
indexing them for history, and distributing agent artifacts to it.

The runtime's own surface — profiles, plugin management, launcher flags, the
headless one-shot contract, and the hook executor's compatibility limits — is
the vendor's, and is documented against the installed binary in
`third-party/deepseek-dsh/runtime-surface` and `third-party/deepseek-dsh/hooks`.

Provisioning steps belong to `local/projects/teleclaude/procedure/onboard-agent-harness`.
Installing and moving the runtime, its TUI and every profile plugin is
installation convergence, owned by reconciliation
(`local/projects/teleclaude/spec/feature/reconciliation/deepseek-stack-convergence`).

## Canonical fields

### Use cases

#### UC-DSH-AGENT-1: An operator can start a session with DeepSeek

```gherkin
Given an operator chooses the enabled DeepSeek runtime for a session
When the session is ready
Then that same session runs DeepSeek and accepts the operator's prompt
```

#### UC-DSH-AUTH-1: runner setup checks DeepSeek authentication

```gherkin
Given DeepSeek is enabled as an agent runtime
When an agent or operator runs the managed-runner setup preflight
Then the DeepSeek CLI authentication state is checked with the other enabled runtimes
And an unusable authentication state is surfaced before managed work is dispatched to DeepSeek
```

### macOS launcher

On macOS `resolve_agent_binary("deepseek")` resolves to the signed
`DeepSeekLauncher.app` bundle rather than the bare binary, so the machine's
permission grants attach to a stable identity across rebuilds. Launch arguments
pass through the launcher unchanged. Bundle construction and signing are owned
by `sdlc/procedure/macos-stable-code-signing`.

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

#### UC-DSH-DISTRIBUTE-1: artifact expansion renders and deploys the DSH master

```gherkin
Given an administrator wants DeepSeek sessions to use the platform's agent guidance
When agent artifacts are distributed to an installed DeepSeek runtime
Then the guidance and applicable artifacts are available when a DeepSeek session starts
And an absent DeepSeek installation receives no deployment
```

#### UC-DSH-SEARCH-1: history search indexes DSH sessions

```gherkin
Given an operator wants to find a past DeepSeek conversation
When they search history for terms
Then matching DeepSeek conversations are available through the DeepSeek filter
And an all-agent search includes them
```

#### UC-DSH-SCOPE-1: DSH transcripts feed scoping and transcript views

```gherkin
Given an operator reviews work performed in a DeepSeek session
When they inspect its conversation and changed-path scope
Then they can read the DeepSeek conversation and see the paths it changed
```

### Commit identity

`GIT_AUTHOR_IDENTITIES` maps `deepseek` to the identity
`deepseek <noreply@deepseek.co>`. The commit path resolves it as the deepseek
agent session's author identity.

### Boundaries

- Managed DeepSeek launches apply the canonical agent definition's
  `launch_environment` on fresh starts, resumes, restarts, handoffs, and pane
  recovery. They open directly in the chat composer, bypassing the single-line
  Launchpad input, so first-message delivery preserves multiline prompts.
- A restricted DeepSeek session remains confined to workspace-write rooted at
  that session's working directory.
- A launched deepseek session reaches the TUI idle prompt, never the TUI's
  first-run guide: agent-CLI configuration records the guide as complete in the
  TUI's per-machine data directory and leaves a record that already marks it
  complete at a newer revision untouched.
- Structured schema-constrained one-shot calls are unsupported by the DeepSeek
  runtime. The headless profile accepts task text and prints a final message,
  but exposes no output-format, schema, response-field, or response-type
  contract. The canonical agent definition records that capability as
  unavailable, and structured one-shot callers receive an explicit unsupported-
  capability refusal rather than an unknown-agent failure.
- DSH transcripts are zstd-compressed; session discovery uses
  `session_pattern **/session.jsonl*` under `~/.dsh/sessions`, and session
  identity/project are read from the transcript's session entry (id, cwd),
  normalized across the `session-` prefix variants of older artifacts.
- Not every artifact under the session root is a session. DSH's session store
  mints `session-<n>` ordinals for delegated child sessions created without an
  explicit id and records the spawning session in `parentSession`; that field
  is the discriminator the per-runtime subagent rule reads, and such a
  transcript is dropped at discovery. The `session-` prefix therefore does not
  imply a UUID follows it — the identity invariant stays a full UUID, and
  non-sessions never reach it.
