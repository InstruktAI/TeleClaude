---
description: A command acting on an object another computer holds is authorized there
  from the caller's relayed principal; the caller is authenticated at the edge.
visibility: internal
---

# Cross-Computer Authorization — Spec

## Required reads

- @docs/local/design/architecture/scoped-roles.md
- @docs/local/spec/feature/identity/command-clearance.md

## What it is

A person or agent on one computer can act on objects another computer holds:
whatever a command addressed to that computer acts on — a session running there or
to start there, an operation it owns, its session listing and history, a todo and
its artifacts in a project there, its jobs, its agents' dispatch status, its
configuration. Such a command is decided by the computer that holds the object
(`local/projects/teleclaude/design/architecture/scoped-roles`): that computer
resolves the caller's roles from its own person registry, company rosters, and
project registry, reads the object's scope from its own records, and applies the
command's person band and the object's rules as one decision
(`local/projects/teleclaude/spec/feature/identity/command-clearance`).

The caller's computer establishes who is calling and carries only the caller's
principal across as identity. It never carries a role or a scope as authority: a
role that travels inside a message's author label is projection, read on the
holding computer for display and record and by no clearance. A session identity is a
handle local to the computer that holds that session, never authority on another.
Authentication completes at the edge. Every identified caller's computer-addressed
request is relayed to the owning computer, which authorizes it. The sending
computer applies no command-role, dispatch-privilege, or dispatch-chain
authorization to a relayed request
(`local/projects/teleclaude/spec/identity-and-auth`), with one exception: it
refuses a worker's request to message or link to a session before relaying
it (`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`).

A session listing or a history read sent to another computer reaches objects whose
owner decides, object by object, whether the caller reaches them. The holding
computer admits it when the command's person band admits the highest role the
caller holds on that computer, and returns each object only when its owner's rule
admits the caller for that object.

Every command and read relayed to another computer carries its principal: the
caller's for a caller's command, and the sending daemon's system principal for a
command the daemon forwards on its own account. A relayed message without a
principal violates the relay contract and is rejected at the transport boundary as
malformed; no role or other fact it carries is read.

## Canonical fields

### Use cases

#### UC-XCA1: A person reads a session transcript on another computer

```
Given a person is authorized to read a session on another computer
When they request its transcript
Then that computer returns the session's conversation
```

#### UC-XCA2: An agent starts a session for a person on another computer

```
Given an agent acting for a person is authorized to start work in a project on another computer
When it starts a session for that work
Then the owning computer creates the session for the person
```

#### UC-XCA3: A session started on another computer holds the role that computer resolves

#### UC-XCA4: Every relayed message carries its principal

#### UC-XCA5: An unreachable computer fails the command for that computer

#### UC-XCA6: A platform administrator's reach on other computers is unchanged

#### UC-XCA7: A person browses sessions and history on another computer

```gherkin
Given a person is authorized to read sessions and history on another computer
When they browse those records there
Then the owning computer returns only records within that person's reach
```

#### UC-XCA8: A person inspects an operation owned by another computer

```
Given a person wants the result of an operation owned by another computer
When they request that operation's status
Then the owning computer returns it when their reach admits it
```

#### UC-XCA9: A person inspects a session record on another computer

```gherkin
Given a person wants to inspect a session held by another computer
When they request that session's record
Then the owning computer returns it when their reach admits it
```

## Known caveats

- A command the daemon forwards on its own account — adapter delivery, direct-conversation bundles, closing a session another computer runs, peer synchronization — carries the daemon's system principal and keeps the trust the daemon relay already extends between computers; this contract decides which facts authorize a caller's command, not which computers trust each other.
- A direct conversation with a session another computer holds reaches that computer only as the daemon's own forwarding, so that computer does not decide it; a `telec sessions send` that opens or closes one naming another computer is judged at platform scope on the caller's computer (`local/projects/teleclaude/spec/feature/identity/command-clearance`).
- Sessions another computer shares with this one are listed here under `local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`, not by this contract.
