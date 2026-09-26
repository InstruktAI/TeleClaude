---
description: Which checkout's code a telec invocation runs — the installed canonical
  checkout for the global command, a checkout's own code only through its own wrapper
  and, from a slug worktree, never against the live home — and how a worktree's change
  is still graded by its own rules.
visibility: internal
---

# Checkout Code Selection — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

An agent reaches TeleClaude through `telec`. The global command runs the installed
canonical checkout's code wherever it is called from, so an ordinary call made while
standing in a slug worktree behaves exactly like the same call made from the canonical
checkout, and undelivered code never reaches the live home through it.

A checkout's own `bin/telec` runs that checkout's code. That is how an agent exercises
its own change by hand, calling the wrapper and nothing more. From a slug worktree the
wrapper never runs against the live home: unless its caller names another home, it
creates a temporary home, runs the worktree's code against it, and removes it when the
command ends. A home that holds no machine configuration starts from a copy of the live
one.

Grading stays self-referential: `telec code lint` and `telec code commit` called from a
worktree hand their lint gate to that worktree's own code, run against a fresh scratch
home of its own, so a change is judged by the rules it carries.

The path this behavior sits on is described in
`project/design/architecture/cli-invocation-boundary`.

## Canonical fields

### Use cases

#### UC-CCS1: An ordinary call from a slug worktree runs the installed code

```gherkin
Given a slug worktree whose code differs from the installed canonical checkout
When an agent standing in the slug worktree invokes the global telec
Then the command runs the installed canonical checkout's code
And the command acts on the directory the agent invoked it from
```

#### UC-CCS2: A worktree's own wrapper runs the worktree's code against a named home

```gherkin
Given a slug worktree whose code differs from the installed canonical checkout
And a home location that resolves somewhere other than the live home
When an operator or platform process invokes the worktree's own telec wrapper with that home, from any directory
Then the command runs the worktree's code against that home
And the worktree's code writes nothing into the live home
```

#### UC-CCS3: A worktree's own wrapper supplies and removes its own temporary home

```gherkin
Given a slug worktree
When an agent invokes the worktree's own telec wrapper with no home set, or with a home that resolves to the live home however it is spelled
Then the worktree's code runs against a temporary home the wrapper created for that call
And the temporary home no longer exists once the call ends, whether the command succeeded or failed
And the call's exit status is the command's own
And nothing in the live home changes
```

#### UC-CCS4: A worktree home without a machine configuration starts from the live one

```gherkin
Given a home a slug worktree's own telec wrapper runs against, its own temporary home or a named one, that holds no machine configuration
When the wrapper is invoked
Then that home holds a copy of the live machine configuration before the worktree's code starts
And nothing else is copied from the live home
And the live machine configuration is unchanged
```

#### UC-CCS5: Grading from a worktree applies the worktree's own rules

```gherkin
Given a slug worktree whose change edits a rule the lint gate applies
When an agent lints or commits that change with the global telec from the worktree
Then the lint gate judges the change by the worktree's version of the rule
And only the checks the acting context selects run
And the grading leaves the live home unchanged
```

#### UC-CCS6

## Known caveats

- A temporary or named home moves only the state rooted in the home. A checkout's todo store and
  the running daemon do not follow it: a probe of a command that writes project state
  or acts through the daemon reaches the live one, which is why such behavior is
  verified after delivery (`project/policy/test-moratorium`).

## See Also

- docs/project/design/architecture/cli-invocation-boundary.md — the invocation path these use cases sit on.
- docs/project/adr/0102-a-telec-wrapper-runs-the-checkout-it-belongs-to.md — why the wrapper's location, not the caller's directory, selects the code.
