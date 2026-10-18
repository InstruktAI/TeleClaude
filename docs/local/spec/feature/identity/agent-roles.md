---
description: The closed catalog of agent session roles — each an explicit set of capabilities
  with an opt-in full reach, a class, and a header label — consulted by every decision
  that reads what a session may do or what kind of session it is.
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
replaces. A role not so marked reaches exactly its set and the capabilities the
catalog gives every role.

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

| Capability             | Reach                                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `docs-read`            | Reading documentation.                                                                                                   |
| `todo-read`            | Listing and showing todos and bugs.                                                                                      |
| `todo-write`           | Creating, updating, freezing, removing and delivering todos; filing bugs and suppressions.                               |
| `artifact-read`        | Reading and diffing todo artifacts.                                                                                      |
| `artifact-write`       | Writing and removing todo artifacts.                                                                                     |
| `stamp`                | Stamping todo state and commit-review verdicts.                                                                          |
| `todo-orchestration`   | Driving a todo state machine.                                                                                            |
| `integration`          | Integrating deliveries to canonical main and reading dirty-path ownership.                                               |
| `maintenance-recovery` | Inspecting and recovering canonical-main maintenance.                                                                    |
| `memory-curation`      | Curating memories and prospects from conversation extractions.                                                           |
| `session-observe`      | Listing and showing sessions, searching history, and reading the fleet's computers, projects and agents.                 |
| `transcript-read`      | Showing the transcript of a named session.                                                                               |
| `operation-read`       | Reading the outcome of an operation one's session started or one's reach admits.                                         |
| `session-act`          | Starting, running, reviving, restarting, ending and messaging sessions other than one's own.                             |
| `self-acts`            | Results, files, unsubscribing, ending and restarting for one's own session.                                              |
| `messaging`            | Messaging a person.                                                                                                      |
| `audio`                | Transcribing supplied audio to text.                                                                                     |
| `jobs`                 | Enabling, disabling and running jobs.                                                                                    |
| `jobs-read`            | Listing jobs and their runtime status.                                                                                   |
| `job-report`           | Reporting the result of a job run.                                                                                       |
| `config`               | Changing configuration, and reading person and company configuration.                                                    |
| `config-read`          | Reading and validating machine, global and project configuration.                                                        |
| `reminders`            | Arming, listing and cancelling reminders.                                                                                |
| `code-check`           | Inspecting code: blast radius, lint and tests.                                                                           |
| `code`                 | Formatting, file declarations and commits.                                                                               |
| `mcp`                  | Listing and calling MCP tools.                                                                                           |
| `peer-talk`            | Sending to and tailing a peer session: the builder a reviewer reviews, the claimant that dispatched it.                  |
| `memories-read`        | Listing, searching, deleting and tracing a person's own memories outside an extraction.                                  |
| `memories-save`        | Saving a memory observation when the human the session works for asks it to. Every role reaches it; no role composes it. |
| `dispatch-worker`      | Starting a session whose role is of class `worker`.                                                                      |

The command families are the catalog's vocabulary; which command declares
which family is the CLI surface schema's.

### Roles

The role catalog is the authority for each role's name, class, explicit
capabilities, full-reach opt-in and identity label. Each entry states its own
composition; a role class describes session behavior and supplies no implicit
command membership.

`full_reach` is an explicit opt-in on the role, independently of its class.
It is available to internal roles whose procedures are not directly exposed to
human input. A role serving a directly human-exposed procedure remains
restricted. An operator redirecting an internal agent's assignment does not
change the role's reach. Treatment of indirectly supplied content belongs to
its own input-handling contract, not an inferred widening or narrowing here.

The label is the role's name in a caller-origin identity header, drawn from
`local/projects/teleclaude/spec/message-headers`.

### Assignment-specific command focus

Each role's explicit set represents the commands needed by the procedures that
declare that role, including their required reads and supported entry duties.
Every role of class `worker` composes the worker baseline the catalog declares
and adds to it what its own assignment needs. The baseline holds no capability
that observes the fleet or starts, revives, restarts or ends another session,
directly or by running a job; peer talk with the sessions a worker serves stays
in it. No worker lists
sessions, searches history, reads the fleet's computers, projects or agents, or
starts another session (UC-AR3). A worker's reach is focus, not integrity
(`general/principle/trust-and-guardrails`): the todo's claim and the object
owners still decide what it may change.

Outside the worker class, sharing a role class grants no shared command set.
Procedures share a role only where its focused surface fits their assignments;
a shared label alone supplies no command membership. The catalog owns the sets,
and command declarations own capability membership, under
`local/projects/teleclaude/design/cli-authorization-matrix`.

Capabilities distinguish commands whose assignment needs differ. Beyond the
worker baseline, a role that needs inspection or verification does not acquire
unrelated mutation commands merely because those commands share a broad
namespace. Ordinary startup, documentation retrieval, reporting, peer
communication and completion remain available wherever the role's procedure
requires them.

The focused set remains explicit for a full-reach role. Full reach broadens
permission independently of that focused set; it never expands the focused set
itself. Restricted roles remain bounded by their explicit sets, with object
guardrails retaining their own authority
(`general/principle/trust-and-guardrails`). The catalog names the capabilities
every role reaches without composing them, currently `memories-save`; they
appear in no focused set, so focused help never lists their commands.

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

#### UC-AR7: Role focus follows the assignment rather than its class

#### UC-AR8: Full reach preserves a separate focused set

#### UC-AR9: Every worker composes the worker baseline

```gherkin
Given an agent session whose role is `artist`
When it runs `telec todo stamp`, `telec sessions result` or `telec code commit`
Then each command is admitted
But `telec computers list`, `telec sessions start` and `telec message` are refused with the not-permitted failure naming `artist` and the verb
```

## Known caveats

- A closed session recorded before procedures declared their roles, whose
  record the migration could not map, stays refused if it is revived; the
  migration (`local/projects/teleclaude/spec/feature/agent_runtime/session-role-migration`)
  reports every such record.

- The explicit set of a full-reach role binds nothing: it is the role's focused
  set, which help presents on request without narrowing the role's reach
  (`local/projects/teleclaude/spec/feature/presentation/cli-help`).

## See Also

- docs/local/spec/feature/identity/command-clearance.md — the gate that admits a role by its capabilities.
- docs/local/spec/feature/agent_runtime/procedure-entry.md — how a session receives the role its procedure declares.
- docs/local/adr/0123-procedures-are-entrypoints-and-roles-are-explicit-capability-sets.md — why roles default to contained and full reach is opt-in.
