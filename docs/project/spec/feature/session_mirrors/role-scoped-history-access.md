---
id: 'project/spec/feature/session_mirrors/role-scoped-history-access'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Role-based filtering of mirror search, listing, and detail lookup. Admins see all mirrors; members see their own and shared ones; everyone else sees only their own. Applied in SQL before rows reach the renderer.'
---

# Role-Scoped History Access — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md
- @docs/project/spec/domain/identity.md

## What it is

History queries are filtered by the caller's role so non-admins cannot
enumerate every stored conversation on the host. The mirror store applies a
SQL clause derived from `caller_email` and `caller_role` to the search, list,
and exact-or-prefix detail lookup queries. The CLI resolves these two values
once per command from the terminal's authenticated session and the global
people configuration.

The three role bands are:

- **Admin** (or unresolved role): no role filter is applied. The caller sees
  every mirror on the host.
- **Member**: filter is `(human_email = :caller_email OR visibility =
  'shared')`. The caller sees their own mirrors plus those explicitly marked
  shared on the upstream session.
- **Anything else** (a known non-admin, non-member role): filter is
  `human_email = :caller_email`. The caller sees only their own mirrors.

## Canonical fields

### Behavioral contract

#### Admin sees all

```
Given the caller's resolved role is HUMAN_ROLE_ADMIN
When the role filter is applied to a search / list / detail query
Then no clause is added to the WHERE list and no bind parameters are touched
And the query returns every mirror that matches the other filters
```

#### Unresolved role behaves like admin

```
Given no terminal identity is set OR the email is not in the people config
When the role filter is applied
Then caller_role is None
And no clause is added to the WHERE list
And the query returns every mirror that matches the other filters
```

#### Member sees own + shared

```
Given the caller's resolved role is HUMAN_ROLE_MEMBER
And caller_email is set
When the role filter is applied
Then the clause "(human_email = :caller_email OR visibility = 'shared')" is appended
And caller_email is bound to the corresponding parameter
And the query returns mirrors whose human_email matches OR whose visibility column is 'shared'
```

#### Non-admin, non-member sees only own

```
Given the caller has any other resolved role (e.g., a custom role string)
And caller_email is set
When the role filter is applied
Then the clause "human_email = :caller_email" is appended
And the query returns only mirrors whose human_email matches the caller
```

#### HTTP search and detail bypass role filtering

```
Given a caller issues GET /api/mirrors/search or GET /api/mirrors/{session_id}
When the route handler executes the search or lookup
Then no caller_email or caller_role is threaded into the store call
And the SQL executes without any role clause
And the response includes every mirror that matches the non-role filters
```

### V1 implementation pointers

- `teleclaude/mirrors/store.py:_apply_role_filter` — the WHERE clause and bind parameter mutator that implements the three-band rule.
- `teleclaude/mirrors/store.py:search_mirrors` — call site for search.
- `teleclaude/mirrors/store.py:get_mirror` — call site for detail lookup.
- `teleclaude/mirrors/store.py:list_mirrors` — call site for listing.
- `teleclaude/constants.py:HUMAN_ROLE_ADMIN` / `HUMAN_ROLE_MEMBER` — canonical role constants.
- `teleclaude/cli/telec/handlers/history.py:resolve_cli_caller_role` — email → role resolution via the global people config.
- `teleclaude/cli/session_auth.py:read_current_session_email` — terminal identity used as `caller_email`.

## Known caveats

- An unauthenticated CLI caller (no `caller_email`) with no role configured
  is treated as admin by `_apply_role_filter` — the role filter only runs
  when `caller_role` is set to a non-admin value. Hosts that rely on CLI
  role enforcement must ensure the people config returns a non-admin role
  for the relevant identities.
- The HTTP `/api/mirrors/*` routes do not apply role filtering at all. Any
  caller that can reach the API socket or the TCP port sees every mirror.
- `visibility = 'shared'` is honored by the role filter but is never set by
  mirror code itself; the column defaults to `'private'`. Shared visibility
  arrives from upstream session metadata copied through
  `get_session_context` at mirror creation time.
- The role filter operates on the mirror row's `human_email` field. Mirrors
  created before identity enrichment landed have NULL `human_email` and are
  invisible to member / non-admin callers.
