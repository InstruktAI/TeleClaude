---
description: Where durable state lives and how it is kept — classified by nature, owner and loss cost, persisted when its loss costs more than local recomputation, in a medium that fits its shape, isolated from the paths people and agents wait on, with a declared scope and lifecycle.
---

# State Storage — Policy

## Rules

### Durable state is classified before it is stored

Before a design gives a piece of state a home, it states:

- **Nature.** Authoritative: the source of truth for a fact. Derived: a cache,
  projection or working copy rebuilt from a named source. External bookkeeping:
  what this system knows about another system's state, such as fingerprints,
  cursors and delivery marks. Transient: in flight within one operation.
- **Owner.** The one component that writes it
  (`sdlc/principle/architectural-defaults`, State has a single owner).
- **Loss cost.** What losing it forces: nothing, recomputation, transfer over
  the network, a repeated external effect, or lost intent.

### Durability follows loss cost

- State whose loss forces more than cheap local recomputation is persisted by
  its owner when it is learned, and survives restarts, installs and crashes.
  Process memory holds only state the process rebuilds at start without network
  transfer or repeated effects, and never the only copy of durable state.
- An external effect whose outcome must be recognised afterwards, such as a
  write to another system or a message sent, is preceded by a durable record of
  the intent. Recovery then completes or recognises the effect instead of
  repeating it or fetching its result again.
- A derived store states how it is rebuilt and what the rebuild costs, network
  transfer included. State of any other nature never lives inside a derived
  store, because rebuilding the store destroys it.

### The medium follows the state's shape

- **A state file** holds state that stays small and bounded, has one writer, is
  read whole or by key, and is never queried across. It is one document per
  owner and scope, written whole and atomically: written beside the previous
  version, then renamed over it.
- **A database** holds state that grows without a fixed bound, takes frequent
  partial updates, has more than one writing process, is queried or indexed, or
  must change several records in one transaction.

### Write isolation follows contention

- The write-isolation unit is the scope within which a store makes writers wait
  on each other; the store's own concurrency model defines it (SQLite: one
  database file). State shares a write-isolation unit only with state of the
  same owning domain and a compatible write pattern.
- Background writers, such as pollers, outboxes, delivery queues and
  maintenance, never share a write-isolation unit with a path a person or an
  agent waits on.
- A domain whose write pattern or lifecycle differs from its neighbours' gets
  its own write-isolation unit. Having fewer files is no reason to share one.

### Scope and lifecycle are declared

- Each piece of state names its scope: one machine, one project, one home, or
  the cluster. State that belongs to a responsibility moving between computers,
  such as serving a project, moves with that responsibility through a defined
  transfer.
- A store that grows names its bound and how its entries retire. Current state
  is kept apart from history, logs and outboxes, so retention prunes history
  and never removes durable state that is still current.

## Rationale

- State kept only in memory, or inside a store that is rebuilt, is lost on a
  restart or a rebuild. When its loss forces network transfer or repeated
  effects, every restart costs traffic, provider budget or duplicated actions
  that nobody chose.
- A crash between an external effect and its record leaves the system unable to
  tell whether the effect happened, so it repeats the effect or reads its result
  again. Recording the intent first leaves recovery a fact to act on.
- A database brings a schema, migrations and a shared write lock; a state file
  brings none of these but is rewritten whole. Matching the medium to the
  state's shape pays each cost only where the state needs what it buys.
- Writers sharing a write-isolation unit wait on each other. A background
  writer sharing one with a waiting path adds its write durations to every
  waiter's latency
  (`sdlc/policy/code-quality-practices`, Concurrency).
- State left behind when its responsibility moves is rebuilt from scratch by
  the new owner, at the cost the rebuild states.
- A store that mixes current state with history is either pruned by age, losing
  current state, or never pruned, growing without bound.

## Scope

All durable state a delivery introduces, relocates or changes, in every
project. An existing store is brought in line when a delivery's change path
touches it (`sdlc/policy/definition-of-done`, structural ratchet) or by work
whose purpose that is.

## Enforcement

- The architecture records each piece of durable state against these rules
  (`sdlc/procedure/lifecycle/prepare/architecture`), and architecture review
  verifies the record (`sdlc/procedure/lifecycle/prepare/review-architecture`).
- Work without a reviewed architecture carries the same record in its plan,
  because where durable state is stored is a structural decision
  (`sdlc/policy/preparation-artifact-quality`, Structural decisions carry
  architecture review).
- Build and commit review reject durable state the design never declared and
  storage that breaks these rules (`sdlc/policy/definition-of-done-lanes`,
  Paradigm-fit assessment).

## Exceptions

- None.
