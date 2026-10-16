---
description: Agents mutate TeleClaude machine configuration only through the telec
  config surface, while the config context owns validation and persistence.
---

# Machine Config Mutation Authority — Policy

## Required reads

None.

## Rules

<!-- planned-change:config-client-command-boundary -->

- TeleClaude machine configuration is agent-operated. Agents inspect and mutate it through the `telec config` surface; they never read, edit, replace, or repair the backing file with shell editors, ad hoc scripts, or direct filesystem APIs.

<!-- change:config-client-command-boundary -->

- TeleClaude machine configuration is agent-operated. Ordinary inspection and mutation use the `telec config` surface and its daemon-owned configuration operations. Direct agent file repair is the recovery exception below.

<!-- /planned-change:config-client-command-boundary -->

- A missing `telec config` capability is a tooling gap, not permission to bypass the surface. The agent records or routes that gap and leaves the file untouched.
- Runtime components outside the config context submit semantic configuration operations. They never receive write authority over the backing file or supply a previously read full-document replacement.
- The config context holds the complete mutation transaction: acquire the file lock, read the latest committed document, parse it, apply the requested operation, validate the complete candidate, serialize it, and atomically replace the file before releasing the lock.
- Validation occurs before replacement. A rejected candidate leaves the committed file unchanged, and a successful mutation requires no follow-up `telec config validate` call.
- `telec config validate` is a standalone diagnostic for existing state. It is not a confirmation step after a successful mutation.
- Provider-returned identifiers and other observed external state are not configuration. Their owning bounded context persists them in its state store rather than writing them into machine configuration.

## Rationale

- One mutation authority prevents stale read-modify-write callers from losing each other’s updates and prevents invalid candidates from reaching the committed file.
- A single agent-facing surface keeps operational guidance executable: every agent knows where to inspect, mutate, and diagnose configuration without learning machine-local file mechanics.
- Keeping observed provider state outside configuration preserves one source of truth for both desired settings and reflected runtime state.

## Scope

- All agents operating TeleClaude machine configuration from any project.
- Every TeleClaude runtime, setup, migration, TUI, adapter, and CLI path that can change machine configuration.

## Enforcement

<!-- planned-change:config-client-command-boundary -->

- Reviewers reject direct machine-config file access by an agent or a runtime component outside the config context.

<!-- change:config-client-command-boundary -->

- Reviewers distinguish an agent's direct recovery edit while the daemon is unavailable from ordinary client or runtime mutation, which remains with the config context.

<!-- /planned-change:config-client-command-boundary -->

- Reviewers reject mutation APIs that accept a caller-owned full-document replacement or validate only after persistence.

<!-- planned-change:config-client-command-boundary -->

- Agent-facing procedures and command guidance route configuration work through `telec config` and never recommend direct file editing as recovery.

<!-- change:config-client-command-boundary -->

- Agent-facing procedures route ordinary configuration work through `telec config` and describe direct agent file repair under the recovery exception.

<!-- /planned-change:config-client-command-boundary -->

## Exceptions

<!-- planned-change:config-client-command-boundary -->

- None.

<!-- change:config-client-command-boundary -->

- When the daemon is unavailable, an agent may inspect and edit the configuration files directly to recover it. This is an agent-operated recovery action, not a fallback implemented in UI or CLI clients. It needs no additional recovery service or command.

<!-- /planned-change:config-client-command-boundary -->
