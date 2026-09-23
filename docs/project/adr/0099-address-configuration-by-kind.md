---
description: Address configuration through its declared kind and instance rather than unrelated command namespaces.
number: 99
date: 2026-09-23
---

# Address Configuration by Kind — ADR

## Context

The configuration command surface names its targets inconsistently. Bare
`telec config get` and `patch` address the machine file, while `config people`
combines person creation, person fields, company roster edits, and invitations.
Project and company setup use different command namespaces, and setup commands
can start analysis sessions as a side effect. An agent cannot derive the target
or effect of a command from one rule.

The company roster already has one authoritative home in company configuration.
Adding more company flags to person creation would make that CLI mismatch more
permanent without changing ownership of the data. The machine configuration
has a different file shape from the four overlays, but it is still a
configuration subject an agent must address explicitly.

## Decision

Configuration resources are addressed by singular declared kind and, where the
kind has multiple instances, by stable instance identity:
`telec config <kind> <operation>`. The kind vocabulary is `computer`, `global`,
`person`, `company`, and `project`. The machine file declares `computer` while
remaining outside overlay-tier composition and context-root resolution.

The common resource operations are `init`, `list`, `get`, and `patch`. `init`
converges an instance's required structure without replacing operator values;
`get` reads the declared subject; `patch` changes that subject through its
owning configuration boundary. A command that prepares configuration does not
start an agent. Agent dispatch is an explicit act under `telec sessions`.

## Consequences

An operator can identify the configuration owner before choosing an operation.
Company membership and project assignments are edited through the company
resource while a person's platform identity and settings remain person data.
The machine configuration requires a declaration and a compatibility path for
existing files, without becoming a fifth overlay tier.

The change is broad: existing commands, callers, help, and documentation must
move together. Operations that send invitations or manage service state need
an explicit home outside the four common resource operations. Existing command
paths cannot silently acquire a different target during the transition.

## Alternatives Considered

- Add company and assignment flags to `config people add`. This keeps creation
  convenient but leaves the company-owned roster behind a person command.
- Keep bare machine `config get|patch` and use plural spaces for other targets.
  This leaves machine configuration implicit and makes CLI names diverge from
  declared kinds.
- Split setup and configuration across unrelated top-level namespaces. This
  can name individual actions precisely, but leaves automation to memorize a
  different route for each kind.
