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

#### UC-ESD1: An operator initializes a company without starting analysis

#### UC-ESD2:

#### UC-ESD3: An explicit session runs analysis

```gherkin
Given an operator wants a project or company to be analyzed
When an authorized caller explicitly starts a session with its analysis procedure
Then the requested session starts through the sessions surface
And setup does not start or duplicate that analysis
```

## Known caveats

- An explicit caller is responsible for deciding whether another analysis
  session is already running. The generic session start surface does not infer
  a per-procedure deduplication rule.

## See Also

- docs/local/spec/feature/config/kind-addressed-configuration.md
