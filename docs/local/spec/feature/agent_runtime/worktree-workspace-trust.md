---
description: Antigravity trusts each slug worktree of a repository whose main checkout
  it already trusts while the worktree exists; the platform adds and removes worktree
  paths only and touches no other trust entry.
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

#### UC-WWT1: A slug worktree follows its repository's trust decision

```gherkin
Scenario: Reuse a trust decision for the main checkout
  Given Antigravity trusts a project's main checkout
  When an agent starts in a slug worktree of that project
  Then the session reaches its composer without asking whether to trust that folder
  And other agent runtimes' trust state is unchanged

Scenario: Leave a new repository to the operator's trust decision
  Given Antigravity does not trust a project's main checkout
  When an agent starts in a slug worktree of that project
  Then the platform does not add the worktree to trusted workspaces
  And the operator is asked whether to trust the folder
```

#### UC-WWT2: A worktree of an untrusted repository receives no trust

#### UC-WWT3: Releasing the worktree removes its trust

#### UC-WWT4

#### UC-WWT5: A renamed worktree remains usable by Antigravity

```gherkin
Given an operator renames a todo whose slug worktree is trusted by Antigravity
When worktree maintenance moves it to the new slug path
Then an Antigravity session started there reaches its composer without a trust prompt
And the former path is removed from Antigravity's trusted workspaces
```

#### UC-WWT6: Maintenance removes trust whose worktree is gone

#### UC-WWT7: An unusable trust store never blocks the worktree

```gherkin
Scenario: Worktree work continues when trust settings are unavailable
  Given Antigravity's trust settings cannot be read, parsed, or written
  When an operator creates, attaches, renames, or releases a slug worktree
  Then the worktree operation completes without changing those settings
```

#### UC-WWT8: Folders other than slug worktrees are never touched

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
