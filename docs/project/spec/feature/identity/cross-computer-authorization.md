---
description: A command acting on an object another computer holds is decided by that computer from the caller's relayed principal; the caller's computer applies only what it alone knows about its own caller.
visibility: internal
delivered_by:
  - relay-scoped-role-decisions
---

# Cross-Computer Authorization — Spec

## Required reads

- @docs/project/design/architecture/scoped-roles.md
- @docs/project/spec/feature/identity/command-clearance.md

## What it is

A person or agent on one computer can act on objects another computer holds: a
session running there, a session to start there, an operation it owns, and the
sessions and history it can list or search. Such a command is decided by the
computer that holds the object (`project/design/architecture/scoped-roles`): that
computer resolves the caller's roles from its own person registry, company rosters,
and project registry, reads the object's scope from its own records, and applies the
command's person band and the object's rules as one decision
(`project/spec/feature/identity/command-clearance`).

The caller's computer establishes who is calling and carries only that across: the
verified principal and, for a session caller, that session's identity. It never
carries a role or a scope. What it decides itself is what only it knows about its own
caller: that the caller is identified, that a session caller's agent role is admitted
by the command's agent band, and that the caller's dispatch chain permits the act
(`project/spec/feature/agent_runtime/session-authority`). Each of these narrows; none
widens what the holding computer decides.

A listing or search sent to another computer is a read across many objects. The
holding computer admits it when the command's person band admits the highest role the
caller holds on that computer, and returns each object only when its owner's rule
admits the caller for that object.

Deciding relayed commands is a capability computers advertise to each other
(`project/spec/feature/reconciliation/fleet-cross-version-interop`). Toward a computer
that does not advertise it, the caller's computer relays nothing it cannot have
decided: it judges the command at platform scope itself, relays it unmarked, in
the form a computer without the capability reads, for a caller holding a platform
role on the caller's computer, and refuses any other caller with a failure that
names that computer. A caller's command or read that reaches a computer carrying
no principal is refused there, whatever build sent it; the refusal names its way
out: update the calling computer, or run the command on the computer that holds
the object.

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

#### UC-XCA2: A person's agent is bounded on both computers

```
Given an orchestrator session acting for a person who holds no platform role and the admin role in one company
When it starts a session on another computer, in a project that company owns there
Then the session is started there
And the same start in a project owned by another company is refused by that computer, naming `customer`
But a worker session acting for the same person is refused the start on its own computer
And nothing is sent to the other computer for the refused worker
```

#### UC-XCA3: A session started on another computer holds the role that computer resolves

```
Given a person holding no platform role, the admin role in one company, and a lower role supplied with a start request by their own computer
When a session is started for that person on another computer, in a project that company owns there
Then the new session's person role is the one that computer resolves for that person and that project
And no role carried with the request raises or lowers it
```

#### UC-XCA4: A relayed command without a principal is refused

```
Given a caller's command or read relayed to a computer, from a computer on any build
When it carries no principal
Then that computer refuses it before acting, and reads no role it carries
And the refusal is reported to the caller for that computer
And the refusal says to update the calling computer or run the command on the computer that holds the object
```

#### UC-XCA5: An unreachable computer fails the command for that computer

```
Given a person runs a command naming a session on another computer
When that computer does not answer
Then the command fails, and the failure names that computer
And the caller's computer does not decide the command in its place
```

#### UC-XCA6: A platform administrator's reach on other computers is unchanged

```
Given a person holding the platform admin role on every computer
When the person runs any command naming another computer
Then the command is admitted and that computer serves it
```

#### UC-XCA7: Another computer answers a listing or search of its own objects

```
Given a person holding no platform role and the admin role in one company
When the person lists sessions naming another computer
Then that computer returns its sessions running in projects that company owns there
And no session running there in a project owned by another company, or in no registered project
And a history search naming that computer is answered by that computer, within its own history scope
And a person holding no role on that computer is refused the listing and the search there
```

#### UC-XCA8: An operation is read on the computer that owns it

```
Given a person holding no platform role and the admin role in one company
And an operation owned by another computer, for a session in a project that company owns there
When the person reads that operation naming that computer
Then that computer returns it
And an operation there for a session in a project owned by another company is answered as not found
```

#### UC-XCA9: A computer that does not decide relayed commands receives none it cannot decide

```
Given a computer that does not advertise that it decides relayed commands
When a person holding no platform role runs a command naming that computer
Then the command is refused on the caller's computer, and the refusal names that computer
And a person holding a platform role on the caller's computer is served by that computer
```

## Known caveats

- A command the daemon forwards on its own account — adapter delivery, direct-conversation bundles, peer synchronization — is not a caller's command and carries no principal. It keeps the trust the daemon relay already extends between computers; this contract decides which facts authorize a caller's command, not which computers trust each other.
- Remote history detail and raw retrieval keep their direct path (`project/spec/feature/session_mirrors/cross-computer-history-federation`) and are not relayed commands; `project/spec/feature/identity/command-clearance` judges them on the caller's computer.
- Sessions another computer shares with this one are listed here under `project/spec/feature/agent_runtime/session-lifecycle`, not by this contract.
