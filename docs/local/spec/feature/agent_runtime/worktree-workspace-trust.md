---
description: Antigravity trusts each slug worktree of a repository whose main checkout
  it already trusts while the worktree exists; the platform adds and removes worktree
  paths only and touches no other trust entry.
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

The platform adds a worktree's path in the step that creates or attaches the
worktree for dispatch, and only when Antigravity already trusts the main checkout
of the worktree's repository; the worktree holds the same repository content, so
the entry extends a decision already made and trusts nothing new. The platform
removes the path in the step that releases the worktree at delivery or removal,
moves it with the worktree when its todo is renamed, and platform maintenance
removes the path of any slug worktree that no longer exists, including one at the
retired location where released worktrees were once parked. A worktree path leaves the list with its worktree whoever added it. The
integration worktree, which no session is started in, the folders a worktree's
home clone occupies, subfolders of a worktree, and every folder outside a
project's slug worktrees are never added or removed.

Every other trusted workspace and every other Antigravity setting stay as they
are, and no other agent runtime's trust state changes.

Trust is a convenience, not a gate. Worktree provisioning, rename, and release
complete whether or not the trust list could be updated, and a session that meets
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

#### UC-WWT3: Releasing the worktree removes its trust

```gherkin
Given a slug worktree's path appears among Antigravity's trusted workspaces
When the worktree is released at delivery or removal
Then the worktree's path no longer appears among Antigravity's trusted workspaces
And every other trusted workspace and every other Antigravity setting is unchanged
```

#### UC-WWT4

#### UC-WWT5: A renamed todo's worktree keeps its trust

```gherkin
Given Antigravity trusts a todo's slug worktree
When the todo is renamed
Then an Antigravity session started in the renamed worktree reaches its composer without asking whether to trust the folder
And the former worktree path no longer appears among Antigravity's trusted workspaces
```

#### UC-WWT6: Maintenance removes trust whose worktree is gone

```gherkin
Given Antigravity's trusted workspaces include the path of a project's slug worktree that no longer exists, at its current location or at the retired location where released worktrees were once parked
When platform maintenance runs
Then that path no longer appears among Antigravity's trusted workspaces
And every entry that is not such a worktree path is unchanged
```

#### UC-WWT7: An unusable trust store never blocks the worktree

```gherkin
Given Antigravity's settings cannot be read, parsed, or written
When the platform creates, attaches, renames, or releases a slug worktree
Then that worktree operation completes as it would without a trust update
And Antigravity's settings are left as they were
```

#### UC-WWT8: Folders other than slug worktrees are never touched

```gherkin
Given Antigravity's trusted workspaces include folders that are not slug worktrees of a project, including the project's main checkout, its integration worktree, a worktree's home clone, and a subfolder of a worktree, whether or not those folders still exist
When the platform creates, attaches, renames, or releases slug worktrees, or maintenance runs
Then those entries remain among Antigravity's trusted workspaces
```

## Known caveats

- Antigravity's exact-path matching is observed on 1.2.14, not vendor-documented;
  a release that changes the comparator makes an entry ineffective or unnecessary
  without breaking a session, because the prompt and its acceptance remain the
  fallback.
- Antigravity rewrites the same settings file without a locking contract; an entry
  lost to a simultaneous rewrite is restored at the worktree's next dispatch.

## See Also

- docs/local/spec/feature/workflow/worktree-prep-lifecycle.md — the worktree
  provisioning and release steps that add and remove the trust.
- docs/local/spec/feature/agent_runtime/isolated-home.md — the other
  per-worktree resource provisioned and retired with the worktree.
