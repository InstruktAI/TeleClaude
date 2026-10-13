---
description: The closed catalog of agent session roles — each an explicit set of capabilities with an opt-in full reach, a class, and a header label — consulted by every decision that reads what a session may do or what kind of session it is.
delivered_by:
  - procedure-role-capability-composition
---

# Agent Roles — Spec

## Required reads

- @docs/local/spec/domain/identity.md

## What it is

An agent session carries at most one role, named for its assignment. The role
catalog is the closed set of roles a session may carry and the one place a
role's reach is composed. A **capability** is one named unit of reach: one
family of `telec` commands, or one grant to start sessions of one class. A
**role** declares an explicit, minimal set of capabilities. A role marked
`full_reach` reaches every capability; its explicit set is then documentation
of the role's ordinary surface and binds nothing, and the focus of such a
session is its procedure's own discipline, with the integrity of shared
objects staying where it always was — with the object guardrails (claims,
driver dedup, singleton leases, extraction scope), which no role filter
replaces. A role not so marked reaches exactly its set.

Every consumer that asks what a role may do or what kind of session it is reads
the catalog and keeps no role list of its own: command clearance
(`local/projects/teleclaude/spec/feature/identity/command-clearance`), run-session
dispatch privilege
(`local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`), a
procedure's role declaration (`general/spec/snippet-authoring-schema`),
standing classification
(`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`),
worker history exclusion, launch ownership and identity-header labelling. Which
commands declare which command capability is the CLI surface schema's, grouped
as `local/projects/teleclaude/design/cli-authorization-matrix` describes.

A role is focus, not integrity (`general/principle/trust-and-guardrails`): it
keeps an agent inside its brief, narrows a person's reach and never widens it,
and leaves every object rule with the object's owner. A human session — one
started by a person and carrying no agent role — reaches every capability and
is bounded by its person band alone.

A role is assigned when its session is created from the procedure the session
enters through (`local/projects/teleclaude/spec/domain/agent_runtime`), or by
one of the two adoption doors that assign a role to a live session: coordinator
acquisition and lifecycle in-place adoption. `system` is the daemon credential's
own identity and is never a session role.

## Canonical fields

### Capabilities

| Capability             | Reach                                                                                                   |
| ---------------------- | ------------------------------------------------------------------------------------------------------- |
| `docs-read`            | Reading documentation.                                                                                  |
| `todo-read`            | Listing and showing todos and bugs.                                                                     |
| `todo-write`           | Creating, updating, freezing, removing and delivering todos; filing bugs and suppressions.              |
| `artifact-read`        | Reading and diffing todo artifacts.                                                                     |
| `artifact-write`       | Writing and removing todo artifacts.                                                                    |
| `stamp`                | Stamping todo state and commit-review verdicts.                                                         |
| `todo-orchestration`   | Driving a todo state machine.                                                                           |
| `integration`          | Integrating deliveries to canonical main and reading dirty-path ownership.                              |
| `maintenance-recovery` | Inspecting and recovering canonical-main maintenance.                                                   |
| `memory-curation`      | Curating memories and prospects from conversation extractions.                                          |
| `session-observe`      | Listing, showing and tailing sessions; searching and showing history.                                   |
| `session-act`          | Starting, running, reviving, restarting, ending and messaging sessions other than one's own.            |
| `self-acts`            | Results, files, ending and restarting for one's own session.                                            |
| `messaging`            | Messaging a person.                                                                                     |
| `jobs`                 | Listing, enabling, running and reporting jobs.                                                          |
| `config`               | Reading and changing configuration.                                                                     |
| `reminders`            | Arming, listing and cancelling reminders.                                                               |
| `code`                 | Code quality, declarations and commits.                                                                 |
| `mcp`                  | Listing and calling MCP tools.                                                                          |
| `peer-talk`            | Sending to and tailing a peer session: the builder a reviewer reviews, the claimant that dispatched it. |
| `dispatch-worker`      | Starting a session whose role is of class `worker`.                                                     |

The command families are the catalog's vocabulary; which command declares
which family is the CLI surface schema's.

### Roles

| Role                                                                                                  | Class    | `full_reach` | Explicit set                                                                                                                                                                       | Label        |
| ----------------------------------------------------------------------------------------------------- | -------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `builder`, `reviewer`, `finalizer`, `diagnoser`, `drift-analyzer`, `artist`, `frontender`, `deferrer` | worker   | no           | `docs-read`, `todo-read`, `todo-write`, `artifact-read`, `artifact-write`, `stamp`, `self-acts`, `reminders`, `code`, `jobs`, `mcp`, `peer-talk`                                   | Worker       |
| `prepare-orchestrator`, `work-orchestrator`, `create-orchestrator`, `intaker`, `architect`, `planner` | agent    | yes          | `todo-orchestration`, `todo-read`, `todo-write`, `artifact-read`, `artifact-write`, `stamp`, `dispatch-worker`, `session-observe`, `session-act`, `docs-read`, `reminders`, `code` | Orchestrator |
| `integrator`                                                                                          | standing | yes          | `integration`, `maintenance-recovery`, `dispatch-worker`, `code`, `session-observe`, `session-act`, `docs-read`, `todo-read`, `todo-write`, `stamp`, `reminders`                   | Integrator   |
| `coordinator`                                                                                         | standing | yes          | `session-observe`, `session-act`, `docs-read`, `todo-read`, `messaging`, `reminders`                                                                                               | Orchestrator |
| `task-preparer`, `task-runner`                                                                        | agent    | yes          | `todo-read`, `todo-write`, `artifact-read`, `artifact-write`, `stamp`, `dispatch-worker`, `docs-read`, `reminders`, `code`                                                         | Tasker       |
| `bug-hunter`                                                                                          | agent    | yes          | `todo-read`, `todo-write`, `docs-read`, `jobs`, `reminders`                                                                                                                        | Job Runner   |
| `installation-inspector`                                                                              | agent    | yes          | `maintenance-recovery`, `docs-read`, `todo-read`, `todo-write`, `jobs`, `reminders`                                                                                                | Integrator   |
| `memory-curator`                                                                                      | agent    | yes          | `memory-curation`, `docs-read`, `reminders`, `self-acts`                                                                                                                           | Tasker       |
| `desk-memory-curator`                                                                                 | agent    | no           | `memory-curation`, `docs-read`, `reminders`, `self-acts`                                                                                                                           | Tasker       |
| `helper`                                                                                              | agent    | yes          | `docs-read`, `todo-read`, `session-observe`, `code`, `reminders`                                                                                                                   | Agent        |

A worker-class role is never marked `full_reach`. The label is the role's name
in a caller-origin identity header, drawn from the closed label vocabulary of
`local/projects/teleclaude/spec/message-headers`.

### Class

A role's class says what kind of session carries it, independently of its
reach. Its consumers are the contracts that own the consequence, each reading
the class and deciding nothing about reach:

- `worker` — a focused session another session dispatched; the target class a
  `dispatch-worker` grant may start, and the class the session-mirrors search
  contract excludes by default.
- `standing` — a session whose work arrives from a queue or the fleet; the
  session-authority contract's standing class. A scheduled job's session is
  standing whatever its role.
- `agent` — every other agent session.

### Resolution

A session's role is read from its record and resolved to its catalog entry. A
recorded role the catalog names carries exactly its composition. A recorded
role the catalog does not name is a platform defect: the session is refused
every role-gated act with the not-permitted failure naming that role, the
refusal is logged as an error naming the session and the value, and the
session is never treated as a human session. Launch ownership reads role
presence: a session with an agent role is an automated launch; a session with
none is a human launch.

### Use cases

#### UC-AR1: A role reaches what its explicit set composes

```gherkin
Given an agent session whose role is `desk-memory-curator`
When it runs a `telec memories` curation command for an extraction prepared for it
Then the command is admitted
But `telec sessions list` is refused with the not-permitted failure naming `desk-memory-curator` and the verb
```

#### UC-AR2: A full-reach role reaches every capability

```gherkin
Given an agent session whose role is `bug-hunter`
When it runs `telec sessions list` or `telec config computer get`
Then each command is admitted
And its explicit set lists neither
```

#### UC-AR3: A worker reaches nothing across the fleet

```gherkin
Given an agent session whose role is `builder`
When it runs `telec sessions list`, `telec history search` or starts another session
Then each command is refused with the not-permitted failure naming `builder` and the verb
```

#### UC-AR4: Only a dispatch grant or full reach starts a worker

```gherkin
Given an agent session whose role is `desk-memory-curator`
When it starts a session whose procedure declares a worker-class role
Then it is refused for lacking the dispatch privilege for that role
And a session whose role is `work-orchestrator` starting the same session is admitted
```

#### UC-AR5: A human session reaches everything within its person band

```gherkin
Given a session a person started that carries no agent role
When the person's effective role admits the command
Then the command is admitted whatever capability it needs
And a session carrying the `customer` band reaches only the desk commands
```

#### UC-AR6: A recorded role outside the catalog grants nothing and is reported

```gherkin
Given a session whose record carries a role the catalog does not name
When an agent inside it runs `telec docs get` for a snippet
Then the command is refused with the not-permitted failure naming that role and the verb
And an error naming the session and the role is logged
And the session is not admitted as a human session
```

## Known caveats

- A closed session recorded before procedures declared their roles, whose
  record the migration could not map, stays refused if it is revived; the
  migration (`local/projects/teleclaude/spec/feature/agent_runtime/session-role-migration`)
  reports every such record.
- The explicit set of a full-reach role binds nothing, and no brief presents
  it: the procedure-entry brief carries the role's framing line and no command
  listing. Presenting the set as a brief's command surface, and narrowing the
  CLI index a session sees to it, is a separate delivery; until it lands the
  set is documentation of the role's ordinary surface.

## See Also

- docs/local/spec/feature/identity/command-clearance.md — the gate that admits a role by its capabilities.
- docs/local/spec/feature/agent_runtime/procedure-entry.md — how a session receives the role its procedure declares.
- docs/local/adr/0123-procedures-are-entrypoints-and-roles-are-explicit-capability-sets.md — why roles default to contained and full reach is opt-in.
