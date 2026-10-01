---
id: third-party/antigravity-cli/directory-trust-1.1.12
type: third-party
scope: project
description: Google Antigravity CLI workspace-trust storage (1.1.12 static) and its exact-real-path matching observed on 1.2.14, with the remaining write-safety gaps.
---

# Google Antigravity CLI 1.1.12 directory trust

## Evidence boundary

This is pinned to the shipped macOS arm64 `agy` 1.1.12 binary at
`~/.local/bin/agy` (SHA-256
`c8fd3c0016e101689f923f82da1c068b0e6dce3abcb0089e282742693ad4d344`, Google
Team ID `EQHXZ8M8AV`). Findings not covered by official documentation come from
static strings and Go type metadata in that signed binary; it was not executed
to derive them.

Sections B and C additionally record behavior observed by executing the
installed `agy` 1.2.14 on macOS arm64 on 2026-10-01, under the real user home:
the CLI was launched in tmux in fresh directories outside any Git repository,
with candidate entries added to `trustedWorkspaces`, and the pane was inspected
for the startup trust menu. A session launched in an untrusted directory was the
negative control; an exact entry for the launch directory was the positive
control.

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

Neither the official documentation nor the shipped type metadata establishes
how a launch directory is stored. On 1.2.14 the lookup compares against the
symlink-resolved launch directory: an entry spelled with the resolved path
(`/private/tmp/...`) suppressed the menu, while an entry for the same directory
spelled through the `/tmp` symlink did not.

## C. Resolution and inheritance

The codelab says the prompt is typically seen in each new folder, but it does
not specify the comparator. On 1.2.14 membership is an exact path match:

| Entry                                   | Launch directory   | Trust menu |
| --------------------------------------- | ------------------ | ---------- |
| none                                    | `<d>/ctrl`         | shown      |
| `<d>/anc` (exact ancestor)              | `<d>/anc/child`    | shown      |
| `<d>/*` (top-level)                     | `<d>/glob1`        | shown      |
| `<d>/*` (top-level)                     | `<d>/nest/deep/er` | shown      |
| `security.trustedWorkspaces: ["<d>/*"]` | `<d>/sec1`         | shown      |
| `<d>/ctrl` (exact, resolved)            | `<d>/ctrl`         | not shown  |

Wildcards are not expanded, ancestors confer no trust, and a nested
`security.trustedWorkspaces` key is not read. Repository-root inheritance was
not probed directly, but a 1.2.13 session launched in a linked worktree of a
repository whose main checkout was listed in `trustedWorkspaces` still showed
the menu, so a linked worktree is not covered by its main repository's entry.

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

- Whether a plain subdirectory inside a Git repository inherits trust from an
  entry for the repository root was not probed.
- The 1.2.14 matching behavior is observed, not vendor-documented, and may
  change between releases.
- Whether `--dangerously-skip-permissions` suppresses the startup trust gate is
  unresolved; documentation only promises tool-permission auto-approval.
- No locking, atomicity, or concurrent-writer contract is documented.

## Sources

- https://codelabs.developers.google.com/antigravity-cli-hands-on
- https://antigravity.google/docs/cli/using?app=cli
- https://github.com/google-antigravity/antigravity-cli/blob/main/README.md
- https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md
