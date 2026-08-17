---
description: 'Role-based filtering of mirror search and detail lookup. Admins see all mirrors; members see their own and shared ones; everyone else sees only their own. Applied at the store boundary before rows reach the renderer, and not bypassable through the on-disk transcript fallback.'
visibility: 'public'
---

# Role-Scoped History Access — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/identity.md

## What it is

History queries are filtered by the caller's role so non-admins cannot
enumerate every stored conversation on the host. The session_mirrors
service applies a filter derived from `caller_email` and `caller_role` to
the search and detail lookups. The CLI resolves these two values once per
command from the terminal's authenticated session and the global people
configuration.

The three role bands are:

- **Admin** (or unresolved role): no role filter is applied. The caller
  sees every mirror on the host.
- **Member**: the filter is "(human_email = caller_email OR visibility =
  'shared')". The caller sees their own mirrors plus those explicitly
  marked shared on the upstream session.
- **Anything else** (a known non-admin, non-member role): the filter is
  "human_email = caller_email".

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

#### UC-RSHA-2: Unresolved role behaves like admin

```
Given no terminal identity is set OR the email is not in the people configuration
When the role filter is applied
Then caller_role is treated as unset
And no clause is added for the role filter
And the query returns every mirror that matches the other filters
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
