---
description: Kimi Code 0.37.2 workspace-trust gate and verified local decision-record shape.
---

# Kimi Code 0.37.2 Directory Trust

## Trust gate

In the installed 0.37.2 TUI, a new untrusted working directory presents a
trust choice before the composer appears: `Trust this folder` or `Don't trust`.
The menu cursor is `❯`, which is a selection marker rather than an idle input
prompt.

## Persistence

The installed Kimi home stores one trust decision per workspace below
`workspace-trust/wd_<name>_<hash>`. The inspected record is a JSON object with
`root` and `trustedAt` fields. Removing that decision record restores the trust
gate for the workspace.

The persisted decision names a workspace, not a repository identity. The
installed `workspaces.json` separately contains a workspace collection and a
deleted-workspace identifier collection; this inspection did not establish any
relationship between those records and trust decisions.

## Gaps

- The vendor reference consulted for this corpus does not specify the trust
  record schema or its path derivation.
- Denied-decision persistence, path normalization, inheritance, and symlink
  behavior were not exercised.

## Sources

- https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html
