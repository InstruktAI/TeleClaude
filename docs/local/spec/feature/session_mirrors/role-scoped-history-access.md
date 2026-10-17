---
description: "Scoping of mirror search and detail lookup by the identity the caller carries. A caller sees the mirrors its reach admits by the subject each mirror's session landed in, and the mirrors recorded under its own principal; a system principal and a platform administrator see every mirror, and a caller that cannot be identified is refused. Every surface that serves mirrors to a caller identifies it first; in-process reads that serve no caller are unscoped."
visibility: 'public'
---

# Role-Scoped History Access — Spec

## Required reads

- @docs/local/spec/domain/session_mirrors.md
- @docs/local/spec/domain/identity.md

## What it is

History queries are scoped to the caller, so no one reads a conversation
without the authority to. The scope derives from the identity the caller carries
— the principal of its session, or the person resolved for it at a terminal —
never from a terminal signal inside a session and never from a stored role copy.
It is the caller's reach (`local/projects/teleclaude/spec/feature/identity/data-visibility`),
resolved when the scope is decided, applied to two facts each mirror carries: the
subject its session landed in — a project, person, or company home, or none —
with that subject's owner, and the principal it is recorded under. A caller's
system role is not an input: it governs which operations the caller may run, not
whose conversations it may read.

The scopes are:

- **System principal and platform administrator**: every mirror on the host. A
  system principal is the platform acting on work that was already accepted; it
  has no person to scope by.
- **Any other person**: the mirrors whose subject their reach admits — their
  company homes, the projects their company administrator role covers or their
  roster assigns them, projects they own, and their own home — whoever those
  mirrors are recorded under; and every mirror recorded under their own
  principal, spawned sessions of their own chains included
  (`general/concept/lineage-vs-authorship`), wherever it was recorded.
- **A mirror with no subject** — its session ran in a folder no registered home
  governs — is visible to a platform administrator, a system principal, and the
  person it is recorded under.
- **A caller that cannot be identified**: refused. Nothing is read and nothing is
  returned; an unidentified caller never receives a wider view than an
  identified one.

Every surface that serves mirrors to a caller identifies that caller first: the
history detail capability that answers `telec history show`, history search,
the search command a peer receives over the relay, and the session_mirrors
service's search, detail, and raw-transcript capabilities. Reads that serve no
caller — mirror generation's check for an existing record, and memory
extraction's transcript read — consider every mirror, because their result
reaches no one.

A filtered miss and an absent mirror are the same outcome to the caller, and
neither reaches past the store. The on-disk transcript discovery is consulted only
for a caller who sees every mirror: a transcript file carries no owner to scope
by, so a scoped caller cannot obtain through the file what the store withheld.

## Canonical fields

### Use cases

#### UC-RSHA-1: A platform administrator sees all

#### UC-RSHA-2: A caller that cannot be identified is refused

#### UC-RSHA-5: The service capabilities scope their caller

#### UC-RSHA-6: A filtered miss does not fall through to the transcript

#### UC-RSHA-7: A system principal sees every mirror

#### UC-RSHA-8: Reads that serve no caller are unscoped

#### UC-RSHA-9: A company administrator sees their company's history

#### UC-RSHA-10: A member sees the sessions their own chain spawned

#### UC-RSHA-11: A mirror with no subject stays at platform scope

#### UC-RSHA-12: A person can find a conversation archived under their identity

#### UC-RSHA-13: A member reads the conversations of the projects they are assigned to

#### UC-RSHA-14: A person's own conversations stay visible outside their reach

## Known caveats

- The scope is decided from the identity the caller carries. A process inside a
  session never presents a terminal login, so a login made on a session's pane
  cannot widen or narrow what that session's processes read (see
  `feature/identity/terminal-email-login`).
- A mirror recorded under no person principal — a system-rooted session's — is
  visible to every person whose reach admits its subject, and to system
  principals.
- A mirror linked to no session attribution records no principal and no
  registered project. It is recorded under the person its own email names — the
  person its session ran under (`feature/session_mirrors/mirror-identity-enrichment`)
  — and has no subject.
- The mirror record's `visibility` value is stored but grants nothing: no scope
  reads it.
