---
id: third-party/claude-code/directory-trust-2.1.229
type: third-party
scope: project
description: Claude Code 2.1.229 workspace-trust storage, path normalization, inheritance, bypass behavior, and write-safety evidence.
---

# Claude Code 2.1.229 directory trust

## Evidence boundary

This is pinned to the shipped macOS arm64 binary at
`~/.local/share/claude/versions/2.1.229` (SHA-256
`d732f0ba0a539c58c2ffcaef06ed03b4e523726f0cb6cc27b3a5b7e7ae0a7a21`,
Anthropic Team ID `Q6L2SF6YDW`, embedded Git SHA
`10b3e93beb60b9548432371b3de664a4190e8da7`). Findings not covered by public
documentation come from static inspection of that bundle; the binary was not
executed to derive them.

## A. Store and value shape

The normal global file is `~/.claude.json` (or the equivalent under
`CLAUDE_CONFIG_DIR`). Trust is nested under a top-level `projects` object whose
keys are path strings. An accepted entry has this shape:

```json
{
  "projects": {
    "/normalized/project/path": {
      "hasTrustDialogAccepted": true
    }
  }
}
```

Acceptance writes the Boolean `true`; missing or false does not establish
persisted trust. Acceptance launched directly in the user's home directory is
session-only and is not written.

## B. Key normalization

The shipped key constructor captures the launch `originalCwd`, finds the
nearest Git root when one exists, and maps a linked worktree to the main
repository root after validating its `.git`, `commondir`, and `gitdir`
metadata. It then applies lexical `path.normalize`; on Windows it also changes
backslashes to forward slashes. Outside Git it uses the lexically absolute
`path.resolve(originalCwd)` followed by the same normalization.

The key constructor does not generally call `realpath`; `realpath` is used only
while validating linked-worktree metadata. The bundle does not separately
document whether its earlier `originalCwd` capture preserves a shell-provided
symlink spelling, so that narrow pre-normalization detail remains open.

## C. Resolution and inheritance

Trust resolution first probes the canonical project key above. It then walks
the lexically normalized current directory through every filesystem parent up
to the root and accepts any ancestor entry whose
`hasTrustDialogAccepted` value is truthy. This is general parent inheritance,
not repository-root-only inheritance. A trusted Git root therefore covers its
subdirectories, but so does any other trusted ancestor. Linked worktrees also
benefit from the main-repository-root probe.

## D. Gate suppression and version history

At 2.1.229, non-interactive execution (`-p`, and the corresponding
non-interactive startup path) establishes session trust and suppresses the
workspace trust dialog. `--dangerously-skip-permissions` and
`--allow-dangerously-skip-permissions` control tool-permission mode; static
startup control flow does not use either flag to satisfy workspace trust.

The public changelog records security fixes around what may load before trust,
and 2.1.225 added the same workspace-trust prompt to `claude agents`. No
authoritative changelog entry was found that dates the introduction of the
`-p` trust bypass or indicates that `--dangerously-skip-permissions` ever
suppressed the core workspace gate.

## E. Third-party writes and concurrency

The shipped binary itself tells operators they may set
`projects[<key>].hasTrustDialogAccepted: true` in `~/.claude.json`, so manual
writing is vendor-shipped operational guidance. Public documentation does not
publish this private field as a stable third-party API or schema.

Claude's own mutation path takes `${configPath}.lock`, re-reads and merges the
file under that lock, detects stale writes, retains timestamped backups, writes
an exclusive same-directory `.tmp.<pid>.<random>` file, flushes it, preserves
mode, and renames it into place. No public specification defines the lock
protocol, timeout/staleness rules, or compatibility obligations for external
writers. A third-party raw writer that ignores the lock can race Claude and
lose unrelated state, including credentials; the private protocol should not
be reimplemented from this minified bundle without an explicit vendor
contract.

## Gaps/Unknowns

- Whether the initial `originalCwd` capture preserves or resolves a caller's
  symlink spelling is not documented, although the subsequent key pipeline is
  statically established.
- Anthropic does not publish a stability or concurrent-writer contract for the
  `projects.*.hasTrustDialogAccepted` field.
- No authoritative version history was found for when `-p` began suppressing
  workspace trust.

## Sources

- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/security
- https://code.claude.com/docs/en/cli-reference
- https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
