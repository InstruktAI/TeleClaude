---
id: 'project/spec/feature/session_mirrors/role-scoped-history-access'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Role-based filtering of mirror search, listing, and detail lookup. Admins see all mirrors; members see their own and shared ones; everyone else sees only their own. Applied at the store boundary before rows reach the renderer.'
---

# Role-Scoped History Access — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/identity.md

## What it is

History queries are filtered by the caller's role so non-admins cannot
enumerate every stored conversation on the host. The session_mirrors
service applies a filter derived from `caller_email` and `caller_role` to
the search, list, and exact-or-prefix detail lookup. The CLI resolves
these two values once per command from the terminal's authenticated
session and the global people configuration.

The three role bands are:

- **Admin** (or unresolved role): no role filter is applied. The caller
  sees every mirror on the host.
- **Member**: the filter is "(human_email = caller_email OR visibility =
  'shared')". The caller sees their own mirrors plus those explicitly
  marked shared on the upstream session.
- **Anything else** (a known non-admin, non-member role): the filter is
  "human_email = caller_email". The caller sees only their own mirrors.

## Canonical fields

### Use cases

#### Admin sees all

```
Given the caller's resolved role is admin
When the role filter is applied to a search / list / detail query
Then no clause is added and no parameters are bound for the role filter
And the query returns every mirror that matches the other filters
```

#### Unresolved role behaves like admin

```
Given no terminal identity is set OR the email is not in the people configuration
When the role filter is applied
Then caller_role is treated as unset
And no clause is added for the role filter
And the query returns every mirror that matches the other filters
```

#### Member sees own + shared

```
Given the caller's resolved role is member
And caller_email is set
When the role filter is applied
Then a clause "(human_email = caller_email OR visibility = 'shared')" is added
And caller_email is bound for the clause
And the query returns mirrors whose human_email matches OR whose visibility is 'shared'
```

#### Non-admin, non-member sees only own

```
Given the caller has any other resolved role (e.g., a custom role string)
And caller_email is set
When the role filter is applied
Then a clause "human_email = caller_email" is added
And the query returns only mirrors whose human_email matches the caller
```

#### Service capabilities bypass role filtering

```
Given a caller invokes the search or detail capability of the session_mirrors service directly
When the capability executes the query
Then no caller_email or caller_role is threaded into the store call
And the store query executes without any role clause
And the response includes every mirror that matches the non-role filters
```

## Known caveats

- An unauthenticated CLI caller (no `caller_email`) with no role
  configured is treated as admin — the role filter only runs when
  `caller_role` is set to a non-admin value. Hosts that rely on CLI role
  enforcement must ensure the people configuration returns a non-admin
  role for the relevant identities.
- The service capabilities do not apply role filtering at all. Any caller
  that can reach a capability endpoint sees every mirror.
- `visibility = 'shared'` is honored by the role filter but is never set
  by the session_mirrors service itself; the field defaults to
  `'private'`. Shared visibility arrives from upstream session metadata
  copied through identity enrichment at mirror creation time.
- The role filter operates on the mirror record's `human_email` field.
  Mirrors created before identity enrichment landed have NULL
  `human_email` and are invisible to member / non-admin callers.
