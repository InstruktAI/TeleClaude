---
description: Every agent assignment starts by naming a procedure — the daemon resolves the procedure's declared role, parameters and dispatch defaults, materializes its complete brief, and creates the session carrying that role before the agent reads a word.
delivered_by:
  - procedure-role-capability-composition
---

# Procedure Entry — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

A procedure entry creates a brand-new agent session whose assignment is a
published procedure. The CLI verb `telec sessions run --command <procedure-id>
--args … --path … --agent … --mode …` names the procedure by its
domain-qualified snippet ID. The daemon resolves that procedure from the
published documentation index, reads the entry declarations its frontmatter
carries — `role`, `parameters`, `dispatch` — binds the arguments, resolves the
role through the agent role catalog
(`local/projects/teleclaude/spec/feature/identity/agent-roles`), checks the
caller's dispatch privilege, selects the agent and thinking mode, materializes
the procedure's complete brief as one artifact, and creates the session with
its role, the procedure as its recorded command, and the resolved invocation
persisted on its launch state. The first thing the agent sees is the loader
naming that brief; the agent reads it verbatim as its instruction set.

Every dispatcher enters through this contract: the lifecycle state machines,
the lifecycle runner, the integration bridge, the scheduled-job runner, the
procedure activation runner, and interactive command input. An entry type adds
typed launch context — a scheduled job's name, an activation's home, subject,
attendance and delivery settings — and the required reads that entry type
implies; it never supplies a role of its own or a wrapper document. No generic
dispatcher command stands between a dispatcher and the procedure.

A session created without a procedure — a conversational start, a generic
create, a desk session — is a human session or a desk session and carries no
agent role. A procedure read inside a session, as a lifecycle hat or as a
dependency, changes nothing about that session: only the launch root supplies
the role and the parameter schema. A live session acquires a role only through
coordinator acquisition or lifecycle in-place adoption. Continuation — restart,
revival, handoff — keeps the stored role and rebuilds the loader from the
persisted invocation.

## Canonical fields

### Ubiquitous language

**Entry procedure**
: A procedure a dispatcher, a job declaration or a subscription names as a launch root. It declares `role`, `parameters` and `dispatch`, and may also be read inline by other sessions.

**Inline read**
: A procedure read inside a session as a hat or a dependency. Whether or not it declares entry fields, none is interpreted and nothing about the session changes; the same procedure may be the launch root of another session.

**Resolved invocation**
: The procedure ID, the bound parameters, the raw argument text, the entry context, the additional context supplied at launch, and the brief reference, persisted on the session's launch state; continuation rebuilds the brief from it in full.

**Brief**
: The one artifact the loader names: the role's framing line, the parameter preamble, the procedure's required-read closure, the entry type's required reads — `general/procedure/scheduled-job-run` for a scheduled job, the event-handling closure the delivery settings imply for an activation — and additional context once. It carries no command listing of its own; what commands the session reaches is the role catalog's decision, and a role-scoped command surface in the brief is a separate delivery (`local/projects/teleclaude/spec/feature/identity/agent-roles`, Known caveats).

**Entry context**
: What the entry type supplies beside the arguments — a job's name, an activation's home, subject, attendance and delivery settings.

### Resolution order

1. The procedure is resolved from the published index. An unknown ID, a pending procedure, a snippet that is not a procedure, or an entry procedure declaring no role refuses the request before a session exists, naming the cause.
2. Arguments are bound to the declared `parameters` once, under the binding rule the schema states (`general/spec/snippet-authoring-schema`): whitespace tokens to positional entries in order, the untokenized remainder to a `rest` entry, defaults for omitted optional entries; the raw text is kept as `$ARGUMENTS`. A missing required parameter or a surplus token refuses the request. An inline read rebinds nothing.
3. The role is resolved through the catalog. A caller carrying a role may start a worker-class target when it holds `dispatch-worker` and any target when it is full-reach; a human session may start anything; no target escapes the check.
4. Agent order and thinking mode resolve through one resolver: an explicit caller mode, then a scheduled job's effective declaration for a job entry, then the procedure's `dispatch` declaration; an entry procedure without one is a publication defect and refuses. Manual preference, automatic preference and fixed continuation keep their meanings.
5. The brief is materialized from that one resolved publication through the context's closure validation; a pending dependency refuses the launch. The brief presents the role by its framing line and nothing about its reach: a full-reach role's focus at entry is its procedure's own discipline, and the integrity of shared objects stays with the object guardrails the brief never restates.
6. The startup instruction is composed in the loader shape — a marker line carrying the procedure ID and the raw arguments, and an instruction to read the brief verbatim as the active instruction set — identical for every runtime.
7. The session is created with `role`, `command` (the procedure ID), `job` (the job name for a scheduled run, the procedure ID for an activation, empty otherwise), `working_slug` where the parameters bind one, `entry_point`, and the resolved invocation.

### Use cases

#### UC-PE1: A session starts with the role its procedure declares

```gherkin
Given a published entry procedure declaring a role the catalog names
When an agent runs `telec sessions run --command <that procedure id> --args <arguments>`
Then one session is created carrying that role
And its recorded command is the procedure ID
And its first instruction is the loader naming the materialized brief
And the brief begins with the role's framing line and contains the procedure's complete closure
```

#### UC-PE2: A scheduled job enters through the same contract

```gherkin
Given a configured agent job whose `job` pointer names an entry procedure
When the job is due and the runner dispatches it
Then the session carries the role that procedure declares
And `job` records the configured job name and the open run is correlated to the session
And the brief includes `general/procedure/scheduled-job-run`, the close-out a job entry implies
And the agent candidates and thinking mode are the job declaration's
```

#### UC-PE3: An activation enters through the same contract

```gherkin
Given a subscribed procedure declaring a role
When its activation runner starts the standing agent for a home
Then the session carries that role
And `job` records the procedure ID and the home, subject, attendance and delivery facts are carried as entry context
And the brief includes the event-handling instructions an activation implies
```

#### UC-PE4: An entry without a usable procedure creates no session

```gherkin
Scenario Outline: Refusal before any side effect
  Given a run request naming <procedure>
  When the daemon resolves it
  Then no session is created
  And the refusal names <cause>

  Examples:
    | procedure                                  | cause                     |
    | an unknown snippet ID                      | the unknown procedure     |
    | a pending procedure                        | its pending state         |
    | a snippet that is not a procedure          | the snippet's type        |
    | an entry procedure declaring no role       | the missing role          |
    | an entry procedure declaring no dispatch   | the missing dispatch      |
```

#### UC-PE5: A missing required parameter refuses the request

```gherkin
Given an entry procedure whose `parameters` declare a required `slug`
When a run request supplies no arguments
Then the request is refused naming the missing parameter
And no session is created
```

#### UC-PE6: Dispatch privilege reads the target role's class

```gherkin
Given a caller whose role holds `dispatch-worker` and is not full-reach
When it runs a procedure declaring a worker-class role
Then the session is created
And when it runs a procedure declaring a role of another class
Then the request is refused naming the dispatch privilege it lacks
And a full-reach caller or a human session is admitted to either
```

#### UC-PE7: An orchestrator starts the integrator when work on main is waiting

```gherkin
Given a session carrying a work-orchestrator role
When it runs the integrator's procedure to clear blocked repo-root synchronization
Then the session is created with the integrator role
And the integrator's singleton lease still decides whether it drains or yields
```

#### UC-PE8: Reading a procedure inside a session changes no role

```gherkin
Given a prepare orchestrator session loads a drafting procedure as its hat
When it reads that procedure
Then its role, parameters and recorded command are unchanged
And no new session is created
```

#### UC-PE9: Continuation rebuilds the loader from the resolved invocation

```gherkin
Given a session created through a procedure entry with bound parameters and entry context
When it is handed off to a successor agent
Then the successor receives a loader naming the same brief
And the bound parameters and entry context are those persisted at creation
```

#### UC-PE10: Interactive input resolves an entry procedure

```gherkin
Given an operator submits a procedure ID and arguments in the TUI New Session modal or through Discord
When the leading token resolves to a published entry procedure
Then the session is created through this contract with that procedure's role
And a token that resolves to no entry procedure remains ordinary conversation
```

#### UC-PE11: A lifecycle script names its worker by procedure ID

```gherkin
Given the work state machine dispatches a build worker
When it emits the dispatch instruction
Then the instruction runs the build procedure by its snippet ID
And the created session carries the `builder` role
```

#### UC-PE12: A target computer without procedure entry refuses before side effects

```gherkin
Given a run request addressed to another computer
And that computer does not advertise the procedure-entry capability
When the request is forwarded
Then it is refused naming the missing capability
And no session or operation is created on either computer
```

#### UC-PE13: A legacy command name is refused by name

```gherkin
Given a run request whose command is a retired command name rather than a procedure ID
When the daemon resolves it
Then the request is refused naming the unknown command
And no session is created
```

### Cross-context references

- **context** — publishes the procedure, its `role`, `parameters` and `dispatch` declarations and its closure; this context resolves and never re-validates them.
- **identity** — owns the role catalog; this context resolves a declared role through it and composes nothing.
- **config** — owns the job declaration whose candidate order and thinking mode a job entry uses.
- **integration** — hands this context an activation with its entry context; the event-delivery contract owns what follows the brief.
- **workflow** — owns the meaning of a bound slug, the worktree binding and the lane a dispatched procedure belongs to.

## Known caveats

- The brief is read by the agent verbatim, whatever its size. It presents no per-role command surface; presenting a role's explicit set in the brief and narrowing the CLI index a session sees is the role-scoped context delivery's concern, not this contract's.
- The legacy `system_role` and `job_role` wire projections stay populated while older computers read them, carrying the class-derived legacy projection the fleet interop contract defines; an older node reads them for display and record and by no clearance, and never creates a session carrying a catalog role.

## See Also

- docs/local/spec/feature/identity/agent-roles.md — the catalog a declared role resolves through.
- docs/local/spec/feature/agent_runtime/procedure-standing-agent.md — the activation runner that enters through this contract.
- docs/local/spec/feature/agent_runtime/scheduled-agent-command-dispatch.md — the scheduled-job runner that enters through this contract.
- docs/local/adr/0123-procedures-are-entrypoints-and-roles-are-explicit-capability-sets.md
