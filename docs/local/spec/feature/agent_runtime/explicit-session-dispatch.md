---
description: Agent sessions start only through the explicit sessions command surface;
  setup and analysis commands do not dispatch implicitly.
---

# Explicit Session Dispatch — Spec

## What it is

`telec sessions` is the CLI front door for starting an agent session. A command
that initializes or changes configuration performs that operation and returns
without starting an agent. Analysis and assessment are activatable procedures;
an agent or operator starts a session explicitly with the applicable procedure
when that work is wanted.

Project and company onboarding follow the same rule: initialization prepares
the subject, and the analysis or assessment it may need is a separate session
started explicitly. No setup command dispatches analysis as a side effect,
including when its source inbox has content. Because a setup command starts no
session, it owns no deduplication guard for one.

## Canonical fields

### Use cases

#### UC-ESD1: Initializing a company starts no agent

```gherkin
Given a company does not yet have its required configuration structure
When an agent initializes the company through the configuration CLI
Then the company structure is established
And no analysis session is started
```

#### UC-ESD2: Reinitializing a project starts no agent

```gherkin
Given a project is already registered and has material available for analysis
When an agent initializes that project again
Then its required setup is converged
And no analysis or assessment session is started
```

#### UC-ESD3: An explicit session runs analysis

```gherkin
Given a project or company has material to analyze
When an authorized caller starts a session with its analysis procedure
Then one requested session is started through the sessions surface
And the setup command does not own or duplicate that dispatch
```

## Known caveats

- An explicit caller is responsible for deciding whether another analysis
  session is already running. The generic session start surface does not infer
  a per-procedure deduplication rule.

## See Also

- docs/local/spec/feature/config/kind-addressed-configuration.md
