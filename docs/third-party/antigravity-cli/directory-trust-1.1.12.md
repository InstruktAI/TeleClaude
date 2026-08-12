---
id: third-party/antigravity-cli/directory-trust-1.1.12
type: third-party
scope: global
description: Google Antigravity CLI 1.1.12 workspace-trust storage and the authoritative gaps that block safe automated trust-store writes.
---

# Google Antigravity CLI 1.1.12 directory trust

## Evidence boundary

This is pinned to the shipped macOS arm64 `agy` 1.1.12 binary at
`~/.local/bin/agy` (SHA-256
`c8fd3c0016e101689f923f82da1c068b0e6dce3abcb0089e282742693ad4d344`, Google
Team ID `EQHXZ8M8AV`). Findings not covered by official documentation come from
static strings and Go type metadata in that signed binary; it was not executed
to derive them.

## A. Store and value shape

The store is `~/.gemini/antigravity-cli/settings.json`. The top-level key is
`trustedWorkspaces`, with an array-of-strings value:

```json
{
  "trustedWorkspaces": ["/absolute/workspace/path"]
}
```

The official codelab shows this exact shape and describes the strings as folders
from which Antigravity CLI was started and accepted as trusted. The shipped Go
binary independently contains the field/tag pair
`TrustedWorkspaces json:"trustedWorkspaces,omitempty"`.

## B. Key normalization

**Open gap.** Neither the official documentation nor the shipped type metadata
establishes whether a launch directory is stored literally, made absolute or
clean, resolved through symlinks, or replaced by a Git/project root. Generic
`filepath.Abs` and `filepath.EvalSymlinks` symbols in the binary are not enough
to attribute either operation to trust-key construction.

## C. Resolution and inheritance

**Open gap.** The codelab says the prompt is typically seen in each new folder,
but it does not specify the comparator. Static inspection did not establish
whether membership requires an exact path, inherits from any ancestor, or uses
an enclosing repository/project root. No automated writer should populate this
store until this rule and section B are established by vendor source or
documentation.

## D. Gate suppression and version history

The official codelab and CLI documentation define
`--dangerously-skip-permissions` as auto-approving tool permissions. They do not
state that it bypasses the separate startup workspace-trust decision. Static
strings confirm the flag's tool-permission description but do not expose enough
control flow to prove whether it suppresses the trust gate. Therefore trust-gate
suppression by this flag is an open gap, not an asserted behavior.

The official changelog through 1.1.12 contains no entry defining a change to
the workspace-trust comparator or a launch flag that bypasses it. Entries about
normalized file URIs, project resolution, and outside-workspace tool approval
concern later permission/project behavior and do not establish directory-trust
matching.

## E. Third-party writes and concurrency

Google's codelab explicitly permits direct edits to `settings.json` and
recommends restarting the CLI afterward; it recommends `/settings` or `/config`
for users who do not want to edit JSON directly. This documents manual file
writing, but not a stable programmatic API.

No authoritative source found documents file locking, atomic replacement,
cross-process serialization, or conflict resolution for this file. Generic
write/rename/lock symbols in a large stripped Go binary cannot safely be tied to
this specific settings path. A concurrent third-party writer therefore has no
vendor-supported safety protocol to follow.

## Gaps/Unknowns

- Path normalization and symlink behavior are unresolved.
- Exact matching versus ancestor or repository-root inheritance is unresolved.
- Whether `--dangerously-skip-permissions` suppresses the startup trust gate is
  unresolved; documentation only promises tool-permission auto-approval.
- No locking, atomicity, or concurrent-writer contract is documented.

## Sources

- https://codelabs.developers.google.com/antigravity-cli-hands-on
- https://antigravity.google/docs/cli/using?app=cli
- https://github.com/google-antigravity/antigravity-cli/blob/main/README.md
- https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md
