---
visibility: internal
number: 0103
date: 2026-09-26
description: A person role means the same at every scope; where it is held bounds what it reaches, so a company administrator is an administrator inside that company's lineage.
---

# Person Roles Are One Vocabulary Held at a Scope — ADR

## Context

Two role vocabularies grew up side by side. The person registry carries a
platform role (`admin`, `member`, `contributor`, `newcomer`), defaulting to
`member`, and every person authorization decision reads it with no notion of
where the caller is acting. The company roster carries a company role (`admin`,
`member`), and its contract declared that role inert: it confers no authority,
is never a visibility tier, and neither role follows from the other. The only
effect a company role had was project coverage for an administrator, consumed by
documentation depth.

The consequence ran in both directions at once. A person onboarded as the
administrator of their own company resolved to platform `member` by default, so
every command band, history scope, and session gate treated them as a member of
the whole platform — admitted to every project, including other companies' —
while their administrative role inside their own company granted nothing but
documentation depth, and not even that for the platform's shared material.

ADR-0067 already moved workflow authorization onto facts read from the object
rather than lists of caller roles. The person side still asked only who the
caller is, never where the object sits.

## Decision

A person role is one vocabulary — `admin`, `member`, `contributor`, `newcomer`,
`customer`, ranked in that order — with the same meaning wherever it is held. A
role is held at a scope: the platform (the person registry) or a company (a
roster membership). The scope bounds what the role reaches; it never changes
what the role means. A company administrator is an administrator for everything
in that company's lineage and an outsider everywhere else.

Every person authorization decision reads the caller's effective role for the
object it acts on: the highest role the person holds at any scope containing
that object, read from the object's own scope, and `customer` where none
contains it. No person holds a role at a scope nobody gave them one at, so the
registry's implicit platform `member` is withdrawn.

## Consequences

- Each surface keeps the one role-capability table it already has; scope is the
  only new input, and it is read from the object, so no surface grows per-scope
  rules.
- Tenancy becomes a property of role resolution: a person holding roles only in
  one company can no longer act on another company's projects through a
  platform-wide default.
- A company administrator maintains their own company's roster and reads its
  lineage in full, including the platform's shared documentation.
- Every consumer that read the platform role directly must change, and the
  session record's stored person role can no longer stand for the person's
  authority everywhere; it becomes a per-object answer.
- A person who relied on the implicit platform `member` without holding it
  anywhere loses platform-wide reach until someone grants them a role.
- The company role vocabulary widens to the full set, which is a configuration
  shape change.

## Alternatives Considered

- **Keep the two vocabularies independent and add company-admin exceptions per
  surface.** Rejected: every surface would re-derive the same scope rule, and
  each new surface would forget one.
- **Promote company administrators to platform administrators.** Rejected: it
  erases the tenancy boundary the company scope exists to draw.
- **Leave the implicit platform `member` in place.** Rejected: it grants
  platform-wide reach to every registered person, which is exactly the scope
  leak this decision closes.
