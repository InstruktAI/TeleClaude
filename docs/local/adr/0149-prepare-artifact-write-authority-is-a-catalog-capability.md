---
visibility: public
number: 0149
date: 2026-10-29
description: A prepare artifact's writer is admitted by the role catalog's prepare-artifact-write capability, which every full-reach role reaches and the diagnoser alone among the focused roles composes, instead of by a role list the artifact write boundary keeps.
---

# Prepare-artifact write authority is a catalog capability — ADR

## Context

ADR-0067 retired the prepare-write job allowlist and made the caller's job role
no input to workflow authorization. ADR-0096 then added the claiming group as
the ownership boundary for every artifact kind, and stated that the
prepare-author role gate continues to decide which members of the group may
write which artifact class. The gate kept its own list of five roles — the
prepare orchestrator and the intake, architecture, diagnosis and planning
authors — and refused every other role-bearing session.

Since then the role catalog has become the one place a role's reach is composed,
with full reach as an explicit opt-in, and every consumer that asks what a role
may do is to read the catalog and keep no role list of its own. The prepare
write gate is a consumer that still keeps one. It refuses full-reach roles the
catalog says reach every capability: a task preparer amending the `input` of an
unheld todo whose contract was open was refused by name.

The role list was also doing a second job that nothing else does. Every focused
role composes the focused baseline, which includes `artifact-write`, because a
focused worker records its outcome in work artifacts such as `review-findings`
and `deferrals`. At the capability layer, then, a builder, a reviewer, a
finalizer, a drift analyzer, an artist, a frontender and a deferrer can all
write artifacts, and the list was the only thing keeping them out of the
prepare artifacts. The diagnoser is the one focused role whose assignment
writes one: it authors the `diagnosis`.

## Decision

Prepare-artifact write authority is a capability of the role catalog,
`prepare-artifact-write`, covering `input`, `prd`, `architecture`, `diagnosis`
and `implementation-plan`. The artifact write boundary admits a prepare-artifact
write from a caller that reaches it: a session whose role's catalog entry
reaches it, a roleless session, or a direct human-identity writer. Every
full-reach role reaches it by its reach. Among the contained roles only the
diagnoser composes it, so every other focused role stays refused. A recorded
role the catalog does not name reaches nothing.

The write boundary keeps no role list. The claim gate and its order are
unchanged: a caller outside a claimed todo's group is refused as a claim
conflict before the capability is consulted.

## Consequences

- A full-reach session — a task preparer, the coordinator, the integrator, a
  helper — writes a prepare artifact of an unheld todo, or of a todo its
  claiming group holds, without the gate naming it.
- No focused role gains a prepare-artifact write it lacked: the diagnoser keeps
  its write, and every other focused role is refused as before, now because its
  catalog entry does not compose the capability.
- The work orchestrator reaches the capability, so the boundary no longer
  refuses it the prepare artifacts of the todo it holds during the build. What
  keeps it out is its brief: the work lane consumes prepare artifacts and
  returns a defect in one through kickback. The boundary already left that
  routing to the lane's convention, and a plan changed after a build started is
  reconciled when the work lane next enters the build.
- A new focused role is refused prepare-artifact writes unless its catalog entry
  composes the capability; a new full-reach role reaches it. Neither needs an
  edit to the write boundary.
- The capability is the catalog's first that no command declares. The command
  `todo artifacts write` still declares `artifact-write`; the write boundary
  adds the capability check for the prepare artifact names.

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
- **Protect the prepare artifacts during a build with a phase condition, as
  ADR-0067 described.** Not taken here: the role list never was a phase rule —
  it refused the work orchestrator at every phase and admitted the human and
  roleless writers at every phase — and a phase closure would be a new
  integrity rule with its own consequences for those writers. The capability
  answers which sessions may write; a phase condition would answer when, and
  remains a separate decision.
