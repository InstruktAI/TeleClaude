---
description: "A program started with no terminal acts as one registered person through an explicit launch door scoped to that program; each command it runs carries that person's live authority, a session's identity always wins, and its requests are never a person's presence."
visibility: 'public'
delivered_by:
  - headless-person-binding
---

# Launched Program Identity — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

A program that runs with no terminal — an unattended installer step, a CI
probe, a command started over SSH, a scheduled script — has no terminal login
to say who it is. The person-launch door starts such a program as one person
already registered on this computer, taking the program and its arguments as
structured arguments and never as a shell string. The program and every
process it starts are then callers outside any session whose identity is that
person.

The binding names the person and nothing else. Every `telec` command run under
it resolves the person against the current roster and passes the ordinary
command gate, so what the person may do is decided at that command from their
roles at that moment (`projects/teleclaude/spec/identity-and-auth` §6). Nothing
supplied at launch — a role, a scope, a session, a claim of human presence —
can add to it.

The binding is an edge identity, like the terminal login, and it ranks below a
session: a process inside a session always acts as its session, and the door
refuses to bind inside one. For the program it launched, it ranks above the
terminal login. It lives only as long as that program and only within that
program's process tree; nothing a later or unrelated process could read is
written anywhere.

Selecting a person is not authenticating them. A process running as the same
operating-system user can already choose a person by logging a terminal in,
and the daemon takes the identity its clients carry as given
(`projects/teleclaude/adr/0101-clients-authorize-and-the-daemon-trusts-carried-identity`).
The door makes that selection explicit and scoped; it proves nothing about who
started the program.

A bound program carries a person's identity, never the person's presence. Its
requests name their own door — distinct from a terminal, the TUI, and an agent
session — so that every consumer of the door can tell a program acting under a
person's name from that person at a keyboard.

## Canonical fields

### Use cases

#### UC-LPI1: A launched program is admitted and refused exactly as its person

```gherkin
Scenario Outline: An unattended program's commands are cleared against its person's live roles and scope
  Given a program started with no terminal through the person-launch door for <person>
  When the program runs <action>
  Then the action is <outcome>
  And a refusal is the ordinary not-permitted failure, with nothing performed

  Examples:
    | person                                   | action                                                         | outcome   |
    | a platform admin                         | a change to platform configuration                             | performed |
    | a company admin holding no platform role | an action their company role admits in that company            | performed |
    | a company admin holding no platform role | a change to platform configuration                             | refused   |
    | a company member assigned to a project   | an action their member role admits in that project             | performed |
    | a company member assigned to a project   | the same action in a project they are not assigned to          | refused   |
    | a registered person with no role grant   | an action every registered person may take                     | performed |
    | a registered person with no role grant   | an action reserved to members                                  | refused   |
```

#### UC-LPI2: A person's authority is read again at every command

```gherkin
Given a program bound through the person-launch door to a company member assigned to a project
And the program has run one command in that project that its member role admits
When an admin withdraws that person's company membership
And the program runs the same command again
Then it is refused with the ordinary not-permitted failure
```

#### UC-LPI3: A person who is not registered cannot be bound

```gherkin
Given no registered person has the address an operator names
When the operator launches a program through the person-launch door for that address, with no terminal
Then the door refuses, naming that no registered person matches
And the program is not started
And no other identity is used in its place
```

#### UC-LPI4: A person removed while their program runs is no longer recognised

```gherkin
Given a program bound through the person-launch door to a registered person
When that person is removed from the roster
And the program runs its next command that requires a caller
Then the command is refused as coming from an unidentified caller
And it does not act as a terminal's person, the sole registered person, or an admin, even when exactly one person remains registered
```

#### UC-LPI5: A binding outranks the terminal its program was started from

```gherkin
Given a terminal whose login names one registered person
When an operator on that terminal launches a program through the person-launch door for another registered person
Then every command the program and its descendants run acts as the bound person
And commands run on that terminal outside the program still act as the terminal's person
```

#### UC-LPI6: The door refuses to bind inside a session

```gherkin
Given a process inside a session, whether its session identity names an open session or is broken
When it launches a program through the person-launch door for a registered person
Then the door refuses, naming that a session already carries its identity
And the program is not started
And the session's processes keep acting as the session, or keep failing as a session with no usable identity
```

#### UC-LPI7: A session never takes its identity from a binding

```gherkin
Given a program bound through the person-launch door to a registered person
When a process inside any session resolves the caller it acts as — a session the program started, or a session process that inherited the binding
Then it acts as the identity its own session carries
And the binding is not consulted
```

#### UC-LPI8: A binding reaches only its own program, and only while it runs

```gherkin
Given one program bound through the person-launch door to one registered person, and a concurrent program bound to another
When each runs commands
Then each acts only as its own bound person
And once a bound program ends, a process started with no terminal outside the door resolves no identity
And no record of either binding remains on the computer
```

#### UC-LPI9: A bound program's requests name the door they came through

```gherkin
Given a program bound through the person-launch door to a registered person
When it runs a command that asks the platform to act
Then the request carries that person as its caller
And it names the person-launch door as the door it came through, never a terminal, the TUI, or an agent session
```

### Cross-context references

- **workflow** — a todo or bug a bound program files records the
  person-launch door and is not human-involved
  (`projects/teleclaude/spec/feature/workflow/todo-creation`).
- **identity** — `telec auth whoami` under the door reports the bound person
  and the headless binding (`projects/teleclaude/spec/feature/identity/whoami-resolution`);
  the terminal login remains the edge identity of a human at a terminal
  (`projects/teleclaude/spec/feature/identity/terminal-email-login`).
- **agent_runtime** — text a bound program sends into a session is delivered
  but never counts as that session's human input
  (`projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`).
- **config** — the roster the binding resolves against is config's; person
  creation and removal stay with the ordinary config surface, and the door
  creates no one.

## Known caveats

- The door is local person selection under the same-user trust boundary
  `projects/teleclaude/spec/identity-and-auth` records in its Known caveats; it
  is not a credential and is never presented as authentication.
- A standing job or any other system work never acquires a person through the
  door by default; a binding exists only where a program was explicitly
  launched through it.
