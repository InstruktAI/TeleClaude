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
(`local/projects/teleclaude/spec/identity-and-auth`).

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

#### UC-XCA1: The computer holding a session decides a person's command on it

```
Given a person holding no platform role and the admin role in one company
And a session running on another computer, in a project that company owns there
When the person runs `telec sessions tail` naming that session and that computer
Then that computer admits the command, and the session's transcript is returned
But the same command naming a session there that runs in a project owned by another company is refused by that computer, naming `customer`
And a person that computer's registry does not hold is refused there, naming `customer`
And no role the person holds on their own computer is consulted by the other computer
```

#### UC-XCA2: The owning computer authorizes a person's agent

```
Given an orchestrator session acting for a person who holds no platform role and the admin role in one company
When it starts a session on another computer, in a project that company owns there
Then the session is started there
And the same start in a project owned by another company is refused by that computer, naming `customer`
And a worker session acting for the same person relays the same request
And the owning computer decides that request from the person's principal by the same rules
```

#### UC-XCA3: A session started on another computer holds the role that computer resolves

```
Given a person holding no platform role, the admin role in one company, and a lower role supplied with a start request by their own computer
When a session is started for that person on another computer, in a project that company owns there
Then the new session's person role is the one that computer resolves for that person and that project
And no role carried with the request raises or lowers it
```

#### UC-XCA4: Every relayed message carries its principal

```
Given a caller's command or read relayed to another computer
Then it carries the caller's principal
And a command the sending daemon forwards on its own account carries that daemon's system principal
And a relayed message carrying no principal is rejected at that computer's transport boundary as malformed, reading no role it carries
```

#### UC-XCA5: An unreachable computer fails the command for that computer

#### UC-XCA6: A platform administrator's reach on other computers is unchanged

```
Given a person holding the platform admin role on every computer
When the person runs any command naming another computer
Then the command is admitted and that computer serves it
```

#### UC-XCA7: Another computer answers a listing or history read of its own objects

```gherkin
Given a person holding no platform role and the admin role in one company
When the person lists sessions naming another computer
Then that computer returns its sessions whose recorded subject the person's reach admits there — a project that company owns there, that company's home, or the person's own home — and the sessions recorded under the person's principal
And no other session there is returned
And a history search or a history show naming that computer is answered by that computer, within the person's reach there
And a person holding no role on that computer is refused the listing and the history reads there
```

#### UC-XCA8: An operation is read on the computer that owns it

```
Given a person holding no platform role and the admin role in one company
And an operation owned by another computer, for a session in a project that company owns there
When the person reads that operation naming that computer
Then that computer returns it
And an operation there for a session in a project owned by another company is answered as not found
And an operation the person's command started there is returned to them, recognised by the principal that command carried
```

#### UC-XCA9: Another computer answers an inspection of its own session

```gherkin
Given a person holding no platform role and the admin role in one company
When the person inspects a session naming the computer that holds it
Then that computer admits the inspection by the same person band and reach as a listing there
And it returns the session's record when the person's reach there admits the session
And it refuses a session there outside the person's reach as outside that reach
And it answers an id that matches no session there as not found
```

## Known caveats

- A command the daemon forwards on its own account — adapter delivery, direct-conversation bundles, closing a session another computer runs, peer synchronization — carries the daemon's system principal and keeps the trust the daemon relay already extends between computers; this contract decides which facts authorize a caller's command, not which computers trust each other.
- A direct conversation with a session another computer holds reaches that computer only as the daemon's own forwarding, so that computer does not decide it; a `telec sessions send` that opens or closes one naming another computer is judged at platform scope on the caller's computer (`local/projects/teleclaude/spec/feature/identity/command-clearance`).
- Sessions another computer shares with this one are listed here under `local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`, not by this contract.
