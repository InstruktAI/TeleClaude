---
visibility: 'public'
description: 'The two session-id namespaces — the TeleClaude session id the platform addresses sessions by, and the agent-native id a mirror is keyed on — which surface accepts which, and where translation between them happens.'
delivered_by: ['telec-history-session-identity']
---

# Session Id Namespaces — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

A session carries two identifiers, and they are never the same value.

- The **TeleClaude session id** is what the platform addresses a session by. It is
  the `session_id` on the session record, the id `telec sessions` verbs accept, the
  id a notification carries, the id stamped into a todo's `lineage`, and the id a
  commit footer records.
- The **agent-native session id** is the identifier the agent runtime assigns its
  own conversation. It names the transcript on disk and it is what a mirror row is
  keyed on, because a mirror is derived from the transcript and outlives the session
  record the platform keeps.

Both are full UUIDs, so neither can be recognised by shape. A caller holding one
cannot tell which it holds without asking the session registry, and the two
populations do not overlap: no session's native id equals its TeleClaude id.

Mirrors stay keyed on the native id deliberately. The session record is ephemeral
and the mirror is durable, so keying the archive on the platform id would make a
conversation unreachable exactly when its session row is gone — which is the case
the archive exists for.

Translation therefore belongs at the edge that receives a caller's id, never in the
store. A surface that accepts an id resolves it against the session registry and
queries the mirror store in the store's own namespace; the store stays a query over
the key it owns.

A session id is a full UUID. A value that is not one is not an identity, and the
boundary where a derived value first becomes an identity refuses it rather than
storing it.

## Canonical fields

### Use cases

#### UC-SIN-1: The two namespaces are disjoint

```
Given any session with both a TeleClaude session id and an agent-native session id
When the two values are compared
Then they differ
And neither can be distinguished from the other by shape, since both are full UUIDs
```

#### UC-SIN-2: A mirror is keyed on the agent-native id

```
Given a transcript is mirrored
When the mirror row is written
Then its session_id column holds the agent-native session id read from the transcript
And the row remains addressable by that id after the session record is gone
```

#### UC-SIN-3: An accepting surface translates; the store does not

```
Given a surface accepts a session id from a caller
And the id belongs to the TeleClaude namespace
When the surface resolves it
Then the surface consults the session registry for that session's native id
And queries the mirror store under the native id
And the mirror store applies no namespace translation of its own
```

#### UC-SIN-4: A derived identity is a full UUID or it is refused

```
Given a transcript that carries a session identity
When the value derived for it is not a full UUID
Then the derivation fails loudly at that boundary
And no row is stored under the non-conforming value
And this is distinct from a transcript carrying no session identity at all, which is stored without one
```

#### UC-SIN-5: A transcript with no session identity keeps its mirror

```
Given a transcript that belongs to no session — a subagent transcript dispatched within a session
When it is mirrored
Then the mirror is stored and its conversation text is retained
And its session id is null, because the store admits a mirror that belongs to no session
And it remains findable by full-text search, which indexes on the row rather than on a session id
And it is not retrievable by session id, since it carries none
```

## Known caveats

- A mirror whose session record has been pruned has no reachable TeleClaude id.
  Such a mirror is addressable by its native id alone, and a surface that prints
  ids states which namespace it is printing.
- Agent runtimes own their transcript filenames and have changed them. A filename
  is a hint about identity, never the identity itself; the authoritative value is
  read from the transcript's own contents.
