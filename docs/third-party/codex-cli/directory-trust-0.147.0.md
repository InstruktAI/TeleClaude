---
id: third-party/codex-cli/directory-trust-0.147.0
type: third-party
scope: project
description: OpenAI Codex CLI 0.147.0 project-trust storage, repository-root lookup, bypass behavior, and write-safety evidence.
---

# OpenAI Codex CLI 0.147.0 directory trust

## Evidence boundary

This is pinned to the open-source tag `rust-v0.147.0`, commit
`be6e8eac029b183056b7e4402879f15d2c85f61b` (released 2026-08-06). Findings
come from static source inspection; the CLI was not executed to derive them.

## A. Store and value shape

The user store is `$CODEX_HOME/config.toml`, normally
`~/.codex/config.toml`. Trust is a TOML table keyed by a path string:

```toml
[projects."/normalized/project/path"]
trust_level = "trusted"
```

`trust_level` is optional and its exact serialized values are `"trusted"` and
`"untrusted"`. An absent value is undecided and triggers the trust screen in
the local TUI; explicit `"untrusted"` is a decision and therefore does not
re-prompt.

## B. Key normalization

For lookup, Codex tries a filesystem-canonical path first
(`Path::canonicalize`, via `normalize_for_path_comparison`) and then the
original path spelling if it differs or canonicalization fails. Windows lookup
keys are lowercased.

When a user accepts trust, the TUI stores the result against the enclosing main
Git repository root when one exists; a linked worktree is resolved through its
`.git` pointer to the main repository root. Outside Git, it stores the resolved
working directory. Thus symlinks are normally resolved for matching, and a Git
subdirectory is represented by its repository root rather than by the launch
subdirectory.

## C. Resolution and inheritance

`ConfigToml::get_active_project` probes exact normalized keys for the resolved
working directory, then exact normalized keys for the resolved main Git
repository root. It does not walk arbitrary filesystem parents.

The proposed lead is therefore **verified**: 0.147.0 resolves the active
project from normalized-CWD lookup plus repository-root lookup. Trust inherited
by a subdirectory is specifically trust for its enclosing Git repository root,
not plain ancestor-directory inheritance. Outside a recognized repository,
only the exact normalized working-directory key matches.

## D. Gate suppression and version history

The 0.147.0 TUI shows the trust screen exactly when
`config.active_project.trust_level.is_none()`. The decision is independent of
approval and sandbox flags. Consequently
`--dangerously-bypass-approvals-and-sandbox` does not suppress this directory
trust gate. `--dangerously-bypass-hook-trust` bypasses the separate startup-hook
review and does not satisfy project trust.

Immediately before the tag, commit `1e59dc5bda` briefly changed undecided local
projects to automatic trust. Commit `17801b4206` restored an explicit prompt,
explaining that trusting enables project-local config, hooks, and exec policies.
The latter behavior is what shipped in 0.147.0. Neither change makes the
dangerous approval/sandbox flag a trust-gate bypass.

## E. Third-party writes and concurrency

Codex exposes supported app-server methods `config/value/write` and
`config/batchWrite`; the latter applies multiple edits atomically to the user
configuration. Requests in one app server are serialized in the global config
lane. There is no dedicated public project-trust mutation method; the TUI uses
an internal `SetProjectTrustLevel` edit.

The direct-file persistence implementation performs read-modify-write and then
writes a same-directory `NamedTempFile` that is persisted by rename. It does
not take an interprocess file lock, and the shown implementation does not call
`fsync`. Atomic replacement therefore does not prevent two processes from
reading the same old file and the later writer losing the earlier writer's
changes. Third-party integration should use the supported app-server config
write surface where possible or provide its own cross-process coordination;
raw concurrent mutation has no vendor-defined safety contract.

## Gaps/Unknowns

- The generic app-server write surface is documented, but OpenAI does not
  document a trust-specific third-party API or compatibility promise for the
  `projects.<path>.trust_level` schema.
- No cross-process locking contract for direct `config.toml` writers is
  documented or present in the inspected persistence path.

## Sources

- https://github.com/openai/codex/tree/rust-v0.147.0
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/config/src/config_toml.rs
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/core/src/config/mod.rs
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/git-utils/src/info.rs
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/tui/src/onboarding/onboarding_screen.rs
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/tui/src/lib.rs
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/core/src/config/edit.rs
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/utils/path-utils/src/lib.rs
- https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/app-server/README.md
- https://github.com/openai/codex/commit/1e59dc5bdaa30c5cc8a488753b3a89c18f77c1bc
- https://github.com/openai/codex/commit/17801b42062f63cf492f3db5df039b6b90779872
