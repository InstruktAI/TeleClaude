---
description: Antigravity trusts each slug worktree of a repository whose main checkout
  it already trusts, from the step that provisions the worktree until the step that
  releases it, and loses only the entries the platform granted.
delivered_by:
  - agy-trusts-platform-worktrees
---

# Worktree Workspace Trust — Spec

## What it is

An agent session started in a todo's slug worktree reaches its composer without
a workspace-trust prompt when its runtime already trusts the repository the
worktree belongs to. Claude Code and Codex resolve a linked worktree to its main
repository and need nothing from the platform
(`third-party/claude-code/directory-trust-2.1.229`,
`third-party/codex-cli/directory-trust-0.147.0`). Antigravity trusts only an
exact, symlink-resolved launch directory and never inherits trust from a main
checkout (`third-party/antigravity-cli/directory-trust-1.1.12`), so the platform
adds each slug worktree to Antigravity's list of trusted workspaces itself.

The platform grants that trust in the step that creates or attaches a slug
worktree for dispatch, and only when Antigravity already trusts the main
checkout of the worktree's repository; the worktree holds the same repository
content, so the grant extends a decision already made and trusts nothing new. The
platform withdraws the grant in the step that releases the worktree at delivery
or removal, moves it with the worktree when its todo is renamed, and platform
maintenance withdraws a grant whose worktree no longer exists. The integration
worktree and directories outside a project's slug worktrees receive no grant.

The platform records which entries it granted and withdraws only those. An
entry the platform did not add, including one accepted at Antigravity's own
prompt, and every other Antigravity setting stay as they are. No other agent
runtime's trust state changes.

A grant is a convenience, not a gate. Antigravity rewrites the same settings
file and publishes no locking contract, so a grant can be lost or fail to land;
worktree provisioning and release complete regardless, and a session that meets
the prompt accepts it under `sdlc/policy/ai-agent-security`.

## Canonical fields

### Use cases

#### UC-WWT1: A worktree of a trusted repository opens without a trust prompt

```gherkin
Given Antigravity trusts the main checkout of a project
When the platform creates or attaches a slug worktree of that project for dispatch
Then an Antigravity session started in that worktree reaches its composer without asking whether to trust the folder
And no other agent runtime's trust state changes
```

#### UC-WWT2: A worktree of an untrusted repository receives no trust

```gherkin
Given Antigravity does not trust the main checkout of a project
When the platform creates or attaches a slug worktree of that project for dispatch
Then Antigravity's trusted workspaces are unchanged
And an Antigravity session started in that worktree asks whether to trust the folder
```

#### UC-WWT3: Releasing the worktree withdraws the trust the platform granted

```gherkin
Given the platform granted Antigravity trust to a slug worktree
When the worktree is released at delivery or removal
Then the worktree's path no longer appears among Antigravity's trusted workspaces
And every other trusted workspace and every other Antigravity setting is unchanged
```

#### UC-WWT4: Trust the platform did not grant survives release

```gherkin
Given a slug worktree's path appears among Antigravity's trusted workspaces without the platform having added it
When the worktree is released at delivery or removal
Then that entry remains among Antigravity's trusted workspaces
```

#### UC-WWT5: A renamed todo's worktree keeps its trust

```gherkin
Given the platform granted Antigravity trust to a todo's slug worktree
When the todo is renamed
Then an Antigravity session started in the renamed worktree reaches its composer without asking whether to trust the folder
And the former worktree path no longer appears among Antigravity's trusted workspaces
```

#### UC-WWT6: Maintenance withdraws trust whose worktree is gone

```gherkin
Given the platform granted Antigravity trust to a slug worktree that no longer exists
When platform maintenance runs
Then that worktree's path no longer appears among Antigravity's trusted workspaces
And every entry the platform did not grant is unchanged
```

#### UC-WWT7: An unusable trust store never blocks the worktree

```gherkin
Given Antigravity's settings cannot be read, parsed, or written
When the platform creates, attaches, renames, or releases a slug worktree
Then that worktree operation completes as it would without a grant
And Antigravity's settings are left as they were
```

## Known caveats

- Antigravity's exact-path matching is observed on 1.2.14, not vendor-documented;
  a release that changes the comparator makes a grant ineffective or unnecessary
  without breaking a session, because the prompt and its acceptance remain the
  fallback.
- A grant lost to a concurrent rewrite by Antigravity itself is restored at the
  worktree's next dispatch. If the same path is accepted at Antigravity's prompt
  before then, the store carries no provenance that tells it apart from the
  platform's grant, and it is withdrawn with the worktree.
- A grant the platform wrote but could not record, because its own bookkeeping
  failed or was interrupted, is treated like an entry the platform did not add and
  stays until removed by hand.
- Worktree entries that predate the platform's record, including paths of
  worktrees already gone, were not granted by the platform and stay until removed
  by hand.

## See Also

- docs/local/spec/feature/workflow/worktree-prep-lifecycle.md — the worktree
  provisioning and release steps that grant and withdraw the trust.
- docs/local/spec/feature/agent_runtime/isolated-home.md — the other
  per-worktree resource provisioned and retired with the worktree.
