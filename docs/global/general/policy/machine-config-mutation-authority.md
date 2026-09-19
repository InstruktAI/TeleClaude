---
description: Agents mutate TeleClaude machine configuration only through the telec config surface, while the config context owns validation and persistence.
delivered_by:
  - move-discord-reflection-state-to-db
---

# Machine Config Mutation Authority — Policy

## Rules

- TeleClaude machine configuration is agent-operated. Agents inspect and mutate it through the `telec config` surface; they never read, edit, replace, or repair the backing file with shell editors, ad hoc scripts, or direct filesystem APIs.
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

- Reviewers reject direct machine-config file access by an agent or a runtime component outside the config context.
- Reviewers reject mutation APIs that accept a caller-owned full-document replacement or validate only after persistence.
- Agent-facing procedures and command guidance route configuration work through `telec config` and never recommend direct file editing as recovery.

## Exceptions

- None.
