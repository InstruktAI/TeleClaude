---
description: 'Role-based filtering of mirror search and detail lookup. A caller that carries an identity is scoped by its role: admins see all mirrors, members see their own and shared ones, and every other role — including one that did not resolve — sees only their own. Applied at the store boundary before rows reach the renderer, and the on-disk transcript fallback is governed by the same outcome.'
visibility: 'public'
---

# Role-Scoped History Access — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/identity.md

## What it is

History queries are filtered by the caller's role so non-admins cannot
enumerate every stored conversation on the host. A caller that carries an
identity supplies `caller_email` and `caller_role`, and the session_mirrors
service derives the filter from those two values for the search and detail
lookups. The CLI resolves them once per command from the terminal's
authenticated session and the global people configuration.

A caller's `system_role` is not an input to this filter. It records the
channel a caller's command authorization came through, and carries no
entitlement to another owner's conversations; the role band is derived from
the human role alone.

Carrying an identity is what distinguishes a scoped caller from an in-process
one. A caller that carries no identity is not role-filtered; that case is
UC-RSHA-5 and is unchanged here.

The role bands, for a caller that carries an identity, are:

- **Admin**: no role filter is applied. The caller sees every mirror on the
  host.
- **Member**: the filter is "(human_email = caller_email OR visibility =
  'shared')". The caller sees their own mirrors plus those explicitly
  marked shared on the upstream session.
- **Anything else** (a known non-admin, non-member role): the filter is
  "human_email = caller_email".
- **Unresolved** (the caller's role did not resolve): the narrowest band
  applies. A caller whose role could not be determined receives no wider view
  than a caller whose role resolved to the most restricted value, and a caller
  carrying no email reaches no mirror at all.

The band governs the detail path's transcript fallback as well as the store
query: a caller the band excludes cannot obtain through the on-disk file what
the store withheld. That outcome is UC-RSHA-6, which states it for every
filtered miss; the unresolved band is one such miss and adds no separate rule.

A filtered miss and an absent mirror are the same outcome to the caller,
and neither reaches past the store: the on-disk transcript discovery is
not consulted for a session the band excluded, so a denied caller cannot
obtain through the file what the store withheld.

## Canonical fields

### Use cases

#### UC-RSHA-1: Admin sees all

```
Given the caller's resolved role is admin
When the role filter is applied to a search or detail query
Then no clause is added and no parameters are bound for the role filter
And the query returns every mirror that matches the other filters
```

#### UC-RSHA-2: A caller whose role does not resolve is held to the narrowest view

```
Given a caller carries an identity whose role cannot be determined
And that caller is a human at a terminal or an agent in a dispatched session
When that caller searches history or requests a session's transcript
Then they see only conversations recorded as their own
And they see no conversation recorded against anyone else
And a caller whose identity names no one reaches no conversation at all
```

#### UC-RSHA-3: Member sees own + shared

```
Given the caller's resolved role is member
And caller_email is set
When the role filter is applied
Then a clause "(human_email = caller_email OR visibility = 'shared')" is added
And caller_email is bound for the clause
And the query returns mirrors whose human_email matches OR whose visibility is 'shared'
```

#### UC-RSHA-4: Non-admin, non-member sees only own

```
Given the caller has any other resolved role (e.g., a custom role string)
And caller_email is set
When the role filter is applied
Then a clause "human_email = caller_email" is added
And the query returns only mirrors whose human_email matches the caller
```

#### UC-RSHA-5: Service capabilities bypass role filtering

```
Given a caller invokes the search or detail capability of the session_mirrors service directly
When the capability executes the query
Then no caller_email or caller_role is threaded into the store call
And the store query executes without any role clause
And the response includes every mirror that matches the non-role filters
```

#### UC-RSHA-6: A filtered miss does not fall through to the transcript

```
Given a caller whose role band excludes a mirror from the detail lookup
When the caller requests that session through the CLI
Then the on-disk transcript discovery is not consulted for that session
And the caller receives the same not-found outcome as for a session that does not exist
And the filtered mirror's transcript is not rendered
```

## Known caveats

- A caller whose identity resolves no role and names no one reaches no
  conversation, whether that caller is a human at a terminal or an agent in a
  dispatched session. Hosts do not depend on the people configuration returning
  a non-admin role to obtain enforcement; an identity that fails to resolve is
  scoped, not exempted.
- The service capabilities do not apply role filtering at all. Any caller
  that can reach a capability endpoint sees every mirror.
- `visibility = 'shared'` is honored by the role filter but is never set
  by the session_mirrors service itself; the field defaults to
  `'private'`. Shared visibility arrives from upstream session metadata
  copied through identity enrichment at mirror creation time.
- The role filter operates on the mirror record's `human_email` field.
  Mirrors created before identity enrichment landed have NULL
  `human_email` and are invisible to member / non-admin callers.
