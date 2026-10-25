---
description: Which checkout's code a telec invocation runs — the installed canonical
  checkout for the global command, a checkout's own code only through its own wrapper
  and, from a slug worktree, never against the live home — and how a worktree's change
  is still graded by its own rules.
visibility: internal
---

# Checkout Code Selection — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

An agent reaches TeleClaude through `telec`. The global command runs the installed
canonical checkout's code wherever it is called from, so an ordinary call made while
standing in a slug worktree behaves exactly like the same call made from the canonical
checkout, and undelivered code never reaches the live home through it.

A checkout's own `bin/telec` runs that checkout's code. That is how an agent exercises
its own change by hand, calling the wrapper and nothing more. From a slug worktree the
wrapper never runs against the live home: the worktree's code runs against the home
repository clone the worktree was provisioned with
(`local/projects/teleclaude/spec/feature/agent_runtime/isolated-home`), whatever home its caller names and
whoever invokes it, and refuses when that home is missing. The wrapper creates no home of
its own.

Grading stays self-referential: `telec repo lint` and `telec repo commit` called from a
worktree hand their lint gate to that worktree's own code, run against that worktree's
home, so a change is judged by the rules it carries with the complete tracked
configuration.

The installed `telec repo lint` and `telec repo commit` commands grade such a
worktree without invoking a second `telec` command; the outer command's caller
clearance governs the grading act. Within the grading act's isolated home, a
selected native leg runs the worktree's own project-native lint, and a selected
guardrail lane runs through one installation-supplied process entry that
confirms it loaded the worktree's code before running exactly that lane.

The path this behavior sits on is described in
`local/projects/teleclaude/design/architecture/cli-invocation-boundary`.

## Canonical fields

### Use cases

#### UC-CCS1: An ordinary call from a slug worktree runs the installed code

```gherkin
Given a slug worktree whose code differs from the installed canonical checkout
When an agent standing in the slug worktree invokes the global telec
Then the command runs the installed canonical checkout's code
And the command acts on the directory the agent invoked it from
```

#### UC-CCS3: A worktree's own wrapper runs against its worktree's home

```gherkin
Given a slug worktree with its provisioned home
When an agent or operator invokes the worktree's own telec wrapper with any home set, or none
Then the worktree's code runs against the worktree's home
And the call's exit status is the command's own
And nothing in the live home changes
```

#### UC-CCS4: A worktree home contains the tracked home repository

```gherkin
Given a slug worktree's own telec wrapper runs against its worktree's home
When the wrapper starts the worktree's code
Then the home contains the tracked project registry and tier configuration documents
And the live home repository is unchanged
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

#### UC-CCS7: A worktree's telec repo commands answer to the worktree's own declaration

```gherkin
Given a slug worktree whose own declaration sets its code, docs, or agents subscriptions differently from its owning checkout
When an agent runs a telec repo command from the worktree
Then whether the command runs, and which checks its quality gate runs, follow the worktree's own declaration
And the owning checkout's declaration is not consulted for that decision
```

#### UC-CCS8: The version report describes one checkout

```gherkin
Given an agent standing in a slug worktree whose HEAD differs from the installed canonical checkout
When the agent runs telec version
Then the reported version and commit both describe the checkout whose code runs
```

#### UC-CCS9: Authorized worktree grading reaches its checks

```gherkin
Given an agent is permitted to run a code quality gate from a slug worktree
When the agent invokes that gate through the global telec
Then the selected checks execute using the worktree's own rules
And grading reports their outcome without an unidentified-caller refusal from its isolated execution
```

## Known caveats

- A worktree or named home moves only the state rooted in the home. A checkout's todo store and
  the running daemon do not follow it: a probe of a command that writes project state
  or acts through the daemon reaches the live one, which is why such behavior is
  verified after delivery (`local/projects/teleclaude/policy/test-moratorium`).

## See Also

- docs/local/design/architecture/cli-invocation-boundary.md — the invocation path these use cases sit on.
- docs/local/adr/0102-a-telec-wrapper-runs-the-checkout-it-belongs-to.md — why the wrapper's location, not the caller's directory, selects the code.
