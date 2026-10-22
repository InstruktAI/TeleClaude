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

The checkpoint evaluation reads the DeepSeek turn transcript and attributes
its tool activity and resulting file changes to the session's workspace. When
an action is due, the Stop response supplies a blocking reason so the runtime
continues the turn with that reason.

The runtime's own surface — profiles, plugin management, launcher flags, the
headless one-shot contract, and the hook executor's compatibility limits — is
the vendor's, and is documented against the installed binary in
`third-party/deepseek-dsh/runtime-surface` and `third-party/deepseek-dsh/hooks`.

Provisioning steps belong to `local/projects/teleclaude/procedure/onboard-agent-harness`.
Installing and moving the runtime, its TUI and every profile plugin is
installation convergence, owned by reconciliation
(`local/projects/teleclaude/spec/feature/reconciliation/deepseek-stack-convergence`).
Artifact distribution leaves machines without an installed DeepSeek runtime
untouched.

## Canonical fields

### Use cases

#### UC-DSH-AGENT-1: An operator can start a session with DeepSeek

```gherkin
Given an operator has enabled DeepSeek and wants to use it for a session
When they start a session with their prompt
Then that session accepts the prompt through DeepSeek
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

#### UC-DSH-CHECKPOINT-2: unmapped DSH stops mint a headless mapping instead of dropping

#### UC-DSH-DISTRIBUTE-1: An administrator can prepare DeepSeek sessions to use platform guidance

```gherkin
Given an administrator wants DeepSeek sessions to use the platform's agent guidance
When they make that guidance and its applicable artifacts available to an installed DeepSeek runtime
Then the guidance and applicable artifacts are available when a DeepSeek session starts
```

#### UC-DSH-SEARCH-1: An operator can find a past DeepSeek conversation

#### UC-DSH-SCOPE-1: An operator can review a DeepSeek session and its changed paths

```gherkin
Given an operator needs to review work performed in a DeepSeek session
When they inspect the session's conversation and changed paths
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
