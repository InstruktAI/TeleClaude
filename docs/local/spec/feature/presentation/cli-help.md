---
description: Discover commands through ordinary help, expand a session's focused role
  set, or expand its permitted surface within an optional namespace.
visibility: internal
---

# CLI Help — Spec

## What it is

CLI help presents the command surface at the detail an agent requests. Command
descriptions, arguments and options come from the CLI surface declaration.
Role focus comes from the agent role catalog
(`local/projects/teleclaude/spec/feature/identity/agent-roles`); permitted reach
comes from command clearance
(`local/projects/teleclaude/spec/feature/identity/command-clearance`). Help
selection consumes those decisions and grants no execution authority.

## Canonical fields

### Selection and detail

Ordinary `telec -h` and command or namespace help retain their complete surface
for full-reach and roleless sessions, subject to their existing caller rules.
A restricted session receives the portion its role permits. The global CLI
help index in the baseline remains in place.

`--expand-role`, used with help, renders detailed help for the calling session's
explicit role set, including when the role has full reach. A session with no
role receives a non-zero error naming the missing role, pointing to
`--expand-all`, and warning that expanding the complete surface can produce
substantial output. An unknown recorded role remains unknown rather than
becoming a roleless caller.

`--expand-all`, used with help, renders detailed help for the caller's permitted
surface. For a full-reach session this includes commands outside its focused
set; for a restricted session it stays within permitted reach. The two expansion
selectors are mutually exclusive.

Either expansion can target the root, a command namespace at any depth, or a
leaf command. Namespace expansion recursively renders the selected descendant
commands, including commands beside nested namespaces, once each in stable
surface order. A selection with no matching commands says so. Expansion reads
help declarations; it executes none of the commands described.

The caller's identity and role are resolved through the identity owner's
contract. The help request chooses detail and namespace, never the identity
whose reach is applied. Selection and rendering are independent of the transport
that delivered the request.

### Assignment context

A procedure directs its agent to retrieve its focused tool help with
`telec -h --expand-role` at the point where that knowledge is needed. The
assignment brief references that retrieval instead of embedding another
rendered command listing. Full-reach agents can retrieve additional command or
namespace help when their work is redirected.

### Use cases

#### UC-CH1: An agent finds help for commands available to its role

```gherkin
Scenario: A role-bound agent consults help for its focused command set
  Given an agent session has an assigned role
  When the agent requests detailed help for its role
  Then the response describes the commands available to that role
  And commands outside that role's permitted surface are absent

Scenario: A roleless agent receives a useful refusal
  Given an agent session has no assigned role
  When it requests detailed help for a role
  Then the response explains that no role is assigned
  And names complete expansion as the available route
  And warns that complete expansion can produce substantial output
```

#### UC-CH2: An agent finds help for work outside its focused role

```gherkin
Given a full-reach agent redirected to work outside its focused role set
When it requests ordinary or expanded-all help for that namespace
Then the response includes the requested commands outside its focused set
And no change of session role is needed to retrieve that help
```

#### UC-CH3: A restricted agent receives only permitted help

#### UC-CH5: An operator explores a command namespace before choosing a command

```gherkin
Given an operator wants to inspect the commands in a namespace before choosing one
When they request expanded help for that namespace
Then each command in the selected namespace and its nested namespaces is described once
And commands outside the selected namespace are absent
And no described command is executed
```

## See Also

- docs/local/spec/feature/identity/agent-roles.md
- docs/local/spec/feature/identity/command-clearance.md
- docs/local/spec/feature/presentation/cli-flag-recognition.md
