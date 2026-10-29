---
visibility: public
number: 0149
date: 2026-10-29
description: A prepare artifact's writer is admitted by the role catalog's prepare-artifact-write capability, which every full-reach role reaches and the diagnoser alone among the focused roles composes, and a todo whose contract is under execution closes its prepare artifacts to every caller, instead of a role list the artifact write boundary keeps.
---

# Prepare-artifact write authority is a catalog capability — ADR

## Context

ADR-0067 retired the prepare-write job allowlist and made authorization the
conjunction of capability, ownership and phase, with the caller's job role no
input. ADR-0096 then added the claiming group as the ownership boundary for every
artifact kind, and stated that the prepare-author role gate continues to decide
which members of the group may write which artifact class. The gate kept its own
list of five roles — the prepare orchestrator and the intake, architecture,
diagnosis and planning authors — and refused every other role-bearing session.
The phase condition was never built: the write boundary enforced no closure of
the prepare artifacts while a build runs.

Since then the role catalog has become the one place a role's reach is composed,
with full reach as an explicit opt-in, and every consumer that asks what a role
may do is to read the catalog and keep no role list of its own. The prepare
write gate is a consumer that still keeps one. It refuses full-reach roles the
catalog says reach every capability: a task preparer amending the `input` of an
unheld todo whose contract was open was refused by name.

The role list was doing two more jobs that nothing else does. Every focused role
composes the focused baseline, which includes `artifact-write`, because a
focused worker records its outcome in work artifacts such as `review-findings`
and `deferrals`. At the capability layer a builder, a reviewer, a finalizer, a
drift analyzer, an artist, a frontender and a deferrer can therefore all write
artifacts, and the list was the only thing keeping them out of the prepare
artifacts; the diagnoser is the one focused role whose assignment writes one. And
by refusing the work orchestrator at every phase, the list stood in for the
missing phase condition: it was the only thing keeping the session that holds a
todo during its build from changing the plan the builder executes.

## Decision

Prepare-artifact write authority has two conditions, beside the unchanged claim.

**Capability.** The role catalog declares `prepare-artifact-write`, covering
`input`, `prd`, `architecture`, `diagnosis` and `implementation-plan`. The write
boundary admits a prepare-artifact write from a caller whose reach, as the
catalog resolves it, includes the capability, or from a direct human-identity
writer. Every full-reach role reaches it by its reach; among the contained roles
only the diagnoser composes it, so every other focused role stays refused.

**Closed contract.** While a todo's lifecycle phase is one of the work lane's,
from build started through finalize ready, its prepare artifacts are writable by
no caller. The refusal names the door: the todo's work orchestrator returns it to
preparation through kickback, and the prepare lane's next call reopens the
contract.

The write boundary keeps no role list. The claim gate keeps deciding first; the
closed-contract refusal follows, then the capability refusal.

## Consequences

- A full-reach session — a task preparer, the coordinator, the integrator, a
  helper — writes a prepare artifact of an unheld todo, or of a todo its
  claiming group holds, while the contract is open, without the gate naming it.
- No focused role gains a prepare-artifact write it lacked: the diagnoser keeps
  its write, and every other focused role is refused as before, now because its
  catalog entry does not compose the capability.
- The work orchestrator reaches the capability, and is kept from the prepare
  artifacts of the todo it builds by the closed contract instead of by its name.
  The same closure binds every other caller, a direct human-identity writer
  included, which narrows what such a writer could do during a build. The
  sanctioned path back is kickback, which already writes its record into `input`
  through the workflow's own store rather than through the write boundary.
- A new focused role is refused prepare-artifact writes unless its catalog entry
  composes the capability; a new full-reach role reaches it. Neither needs an
  edit to the write boundary.
- Like `dispatch-focused`, the capability is declared by no command: the command
  `todo artifacts write` still declares `artifact-write`, and the write boundary
  consults `prepare-artifact-write` for the prepare artifact names.

## Alternatives Considered

- **Delete the gate and rely on the claim alone.** Rejected: a focused worker is
  a member of its dispatcher's claiming group and holds `artifact-write`, so a
  builder or a reviewer would reach the `prd` and the `implementation-plan` of
  the todo it serves. That is the interference the claim cannot see, because the
  writer is inside the group.
- **Refuse the focused class, with the diagnoser as a named exception.**
  Rejected: it keeps a role name in the gate, the structure whose growth
  ADR-0067 identified as the defect, and it reads the caller's class where the
  catalog already composes each role's reach.
- **Split `artifact-write` into a work-artifact and a prepare-artifact command
  capability.** Rejected: one command writes both classes, distinguished only
  by the artifact name it is given, so a command capability cannot express the
  split without dividing the command.
- **Keep refusing the work orchestrator by name to protect the build.**
  Rejected: the protection concerns the contract under execution, not the
  caller, and a name-based refusal leaves every other writer, a human-identity
  writer included, free to change a plan while it is being built. The lifecycle
  phase records that state directly.
