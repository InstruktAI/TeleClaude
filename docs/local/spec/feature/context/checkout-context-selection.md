---
description: Development sessions receive their authoring checkout's contract view while operational sessions and installed agent outputs remain aligned to the installed release.
delivered_by:
  - release-development-checkouts
---

# Checkout Context Selection — Spec

## What it is

Context selection distinguishes the installation's contract generation from the
development checkout's authoring generation. Each invocation consumes one
coherent view selected from its registered checkout purpose. Context consumes
config's association and workflow's resolved roots rather than discovering a
second project from a cloned declaration
(`local/projects/teleclaude/design/architecture/command-scope`).

## Canonical fields

- An operational session receives the installed release's documentation and
  agent artifacts. A development session receives its authoring checkout's
  documentation and applicable agent instructions, including targeted pending
  contracts under `general/policy/context-retrieval`.
- Development indexing and instruction composition have checkout-owned outputs.
  They do not publish that clone as another owner of the same global domains or
  replace the installation's deployed runtime outputs. The installation owns
  machine-wide activation of its project's documentation and artifacts
  (`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`).
- Session bootstrap, explicit documentation reads and worker required-read
  resolution use the same selected context. An unavailable selected generation
  reports the missing context; it is not silently substituted with the other
  checkout's view (`sdlc/principle/design-fundamentals`).
- A todo worktree uses its owning development checkout's doc layer. Its code
  and grading still use the worktree's own source contract
  (`local/projects/teleclaude/spec/feature/agent_runtime/checkout-code-selection`).
- Other projects' activated contributions retain their existing publication
  ownership. The association changes how this project's two checkouts are
  selected; it grants neither broader documentation reach nor another publisher.

### Use cases

#### UC-CCX1: Development and operation read their selected contracts

```gherkin
Given a development checkout describes behavior newer than its installed release
When a development agent and an operational agent retrieve that project's contracts
Then the development agent receives the authoring checkout's view
And the operational agent receives the installed release's view
```

#### UC-CCX2: Development publication preserves installed instructions

```gherkin
Given an operational agent uses the installed release's instruction generation
When development maintenance builds a newer documentation and instruction generation
Then that newer generation is available to development sessions
And the installed instruction generation remains unchanged
```

#### UC-CCX3: A missing development view is explicit

```gherkin
Given a development agent's selected contract generation is unavailable
When the agent retrieves its required context
Then it receives the unavailable-generation diagnostic
And no installed-release view is presented as the requested development contract
```

## Known caveats

- New documentation is not a new runtime API. Commands still execute through
  the installed controller under its own supported contract.
