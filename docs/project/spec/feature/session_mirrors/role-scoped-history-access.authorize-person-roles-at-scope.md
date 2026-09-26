---
description: "Scoping of mirror search and detail lookup by the identity the caller carries. A person whose effective role for a mirror's project is admin sees that mirror, a system principal sees every mirror, every other person sees only their own, and a caller that cannot be identified is refused. Every surface that serves mirrors to a caller identifies it first; in-process reads that serve no caller are unscoped."
visibility: 'public'
---

# Role-Scoped History Access — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/identity.md

## What it is

History queries are scoped to the caller, so no one reads another person's
conversations without the authority to. The scope derives from the identity the
caller carries — the principal of its session, or the person resolved for it at a
terminal — never from a terminal signal inside a session and never from a stored
role copy. A person's role is their effective role for the project each mirror
was recorded in, resolved when the scope is decided
(`project/design/architecture/scoped-roles`). A caller's system role is not an
input: it governs which operations the caller may run, not whose conversations it
may read.

The scopes are:

- **System principal**: every mirror on the host. A system principal is the
  platform acting on work that was already accepted; it has no person to scope
  by.
- **A person whose effective role for a mirror's project is admin**: that mirror,
  whoever it is recorded against. A platform administrator holds that role for
  every project and so sees every mirror; a company administrator sees the
  mirrors of every project their company owns. A mirror recorded against no
  person — a system-rooted session's — is visible to such a person, and to a
  system principal, only.
- **Any other person**: only the mirrors recorded against their own email,
  whatever their role, including a role that does not resolve.
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

#### UC-RSHA-1: Admin sees all

```
Given the caller holds the admin platform role
When the role filter is applied to a search or detail query
Then no clause is added and no parameters are bound for the role filter
And the query returns every mirror that matches the other filters
```

#### UC-RSHA-2: A caller that cannot be identified is refused

```
Given a human at a terminal or an agent in a session whose identity resolves to no person and no system principal
When that caller searches history, requests a session's conversation, or requests its raw transcript
Then the request is refused
And no conversation is returned and no on-disk transcript is consulted
```

#### UC-RSHA-3: A member sees only their own

```
Given the caller is a person whose role is member
When the caller searches history or requests a session's conversation
Then only conversations recorded against the caller's email are returned
And no conversation recorded against another person is returned, whatever else its record carries
```

#### UC-RSHA-4: Any other person sees only their own

```
Given the caller is a person whose role is neither admin nor member, or does not resolve
When the caller searches history or requests a session's conversation
Then only conversations recorded against the caller's email are returned
```

#### UC-RSHA-5: The service capabilities scope their caller

```
Given a caller invokes the search, detail, or raw-transcript capability of the session_mirrors service
When the capability runs
Then it identifies the caller as every authenticated operation does
And it answers within that caller's scope
And a mirror outside that scope is reported exactly as an absent one
And a caller it cannot identify is refused before any mirror is read
```

#### UC-RSHA-6: A filtered miss does not fall through to the transcript

```
Given a caller whose role band excludes a mirror from the detail lookup
When the caller requests that session through the CLI
Then the on-disk transcript discovery is not consulted for that session
And the caller receives the same not-found outcome as for a session that does not exist
And the filtered mirror's transcript is not rendered
```

#### UC-RSHA-7: A system principal sees every mirror

```
Given an agent in a session whose lineage roots at the platform's principal — a standing role, or a session one started
When it searches history or requests a session's conversation
Then every mirror on the host is eligible, including mirrors recorded against no person
```

#### UC-RSHA-8: Reads that serve no caller are unscoped

```
Given the mirror generator checks for an existing mirror of a transcript it is processing
Or memory extraction reads a session's transcript through that session's mirror
When the lookup runs
Then it considers every mirror, whoever it is recorded against
And its result reaches no caller
```

#### UC-RSHA-9: A company administrator sees their company's history

```
Given the caller holds no platform role and the admin role in one company
When the caller searches history or requests a session's conversation
Then mirrors recorded in any project that company owns are returned, whoever they are recorded against
And mirrors recorded in a project owned by another company are returned only when recorded against the caller's own email
```

## Known caveats

- The scope is decided from the identity the caller carries. A process inside a
  session never presents a terminal login, so a login made on a session's pane
  cannot widen or narrow what that session's processes read (see
  `feature/identity/terminal-email-login`).
- A mirror recorded against no person — a system-rooted session's, or one created
  before identity enrichment populated `human_email` — is visible only to a person
  whose effective role for its project is admin, and to system principals.
- The mirror record's `visibility` value is stored but grants nothing: no scope
  reads it.
- A peer applies this same scope to the identity relayed with a remote search (see
  `feature/session_mirrors/cross-computer-history-federation`).
