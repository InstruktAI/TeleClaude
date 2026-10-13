---
visibility: internal
number: 0123
date: 2026-10-13
description: Every agent assignment is entered by naming a procedure that declares its role; roles are composed centrally from explicit capability sets with an opt-in full reach, and the command artifact layer is retired.
---

# Procedures Are Entrypoints and Roles Are Explicit Capability Sets — ADR

## Context

Agent sessions were started by command name. A command artifact was a framing
line plus one procedure required read; the session's role came from a
command-to-role registry, never from the procedure. Scheduled jobs and
event-activated procedures went through two generic dispatcher commands that
fixed one role for every job (`job_runner`) and every activation (`tasker`) and
told the agent to load the real procedure afterwards. Reading the procedure
did not change the persisted role, so an installation inspector, a memory
curator and a bug hunter all ran as the generic dispatcher's role.

Reach was held in two vocabularies (`SystemRole`, `JobRole`) joined per
command, and in a dozen further tables: CLI reach groups, a dispatch matrix, a
standing-role set, literal role checks in hooks and commit guidance, and label
maps. The `job` column carried four meanings. A human steering a session was
bounded by role tables that existed to keep automation focused, which cost
developer experience; a role unknown to a table fell through to roleless, which
on a system-principal session meant admit-all.

An interim that read the targeted procedure's frontmatter from behind the
command facade, then retired the facade later, would build the indirection
twice.

## Decision

- **A procedure is the entrypoint.** Every assignment starts by naming a
  published procedure by its domain-qualified ID. The daemon resolves the
  procedure's declared `role`, `parameters` and `dispatch` before the session
  exists, materializes the procedure's complete brief, and creates the session
  carrying that role. Scheduled jobs, activations, lifecycle dispatch,
  interactive input and hand-started runs all enter this way; an entry type
  adds typed context and implied required reads, never a role. The command
  artifact kind, the global command corpus and the generic dispatchers are
  retired in the same delivery.
- **One role per session, named for its assignment.** The separate role
  vocabularies converge; `job` keeps instance identity only.
- **Roles are explicit capability sets composed in one catalog.** A capability
  is one command family or one dispatch grant. A role lists its set and may be
  marked `full_reach`, in which case it reaches every capability and the set is
  the command surface its brief presents. Reach defaults to contained; full
  reach is opt-in and is declared on the role, never on a procedure.
- **A human session reaches everything within its person band.** Roles keep
  automation focused; they never bound the person.
- **A recorded role the catalog does not name is a platform defect**: refused
  and error-logged, never treated as roleless.
- **Role is focus, not integrity.** Object guardrails stay with their owners;
  defence against untrusted input belongs to runtime isolation and content
  screening, not to the role.

## Alternatives Considered

- **One role per procedure.** Rejected: desk variants of one assignment would
  carry roles indistinguishable in every respect; a role names an assignment.
- **Roles shared by capability profile.** Rejected: the bug hunter would again
  ride a generic role, and a role's identity would change whenever its set did.
- **The flag on the procedure (`handles_unsafe_input` plus a capability list in
  frontmatter).** Rejected: composition would leave the catalog and trust would
  become each author's self-declaration; a flag on the role is decided once
  and reviewed in one place.
- **Finer dispatch grants per session class.** Rejected: only agents dispatch
  workers; every other class is started by platform automation or a full-reach
  session.
- **Keeping the command facades and reading the procedure's role through
  them.** Rejected: it builds the indirection to remove it later.
- **A legacy translation adapter for cross-version dispatch.** Rejected: the
  fleet contract already refuses a command a peer lacks the capability for,
  before any side effect; retaining facades for that case reintroduces what
  this decision removes.

## Consequences

- Capability composition has one owner; every clearance, dispatch, standing,
  history and attribution decision reads it.
- Procedures carry entry declarations; a procedure that no dispatcher names
  declares none and changes no session that reads it.
- Opening the former reservations is a control relaxation and takes a
  no-stake reviewer's approval under `sdlc/policy/process-change-authority`.
- Stored session records receive one forward migration; rows it cannot map
  stay refused and are reported.
- Older computers receive the new role on an additive wire field; the legacy
  projections carry the role name verbatim for transport and are authority for
  nothing.
- Presenting a role's explicit set as its brief's command surface, and
  narrowing the CLI index a session sees, is a dependent follow-up.
