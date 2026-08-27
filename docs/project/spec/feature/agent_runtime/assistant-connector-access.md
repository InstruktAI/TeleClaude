---
description: "How an agent session reaches a person's mail and calendar connectors: a mediated launch that binds every invocation to one resolved person's state and refuses, fail-closed, the operations the personal-assistant conduct gates forbid."
delivered_by:
  - personal-mail-tool-launcher
---

# Assistant Connector Access — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The behavioral contract for how an agent session acting as someone's assistant
reaches the mail and calendar connectors. An agent never touches a connector
binary directly: invoking one by name reaches a mediated launch that resolves
whose assistant is acting, binds the connector's credential and connection
state to that person alone, and refuses the operations the personal-assistant
conduct gates forbid — the initiative send and every settings change — on every
path the connector offers, including its generic pass-through request surface.
An invocation whose effect cannot be established as permitted is refused rather
than attempted.

**Business value:** the conduct policy promises that its gates are enforced
where the tool runs. Connectors differ in what they enforce for themselves, and
one that isolates nothing will, on a missed configuration, write one person's
credentials into another's store and act as the wrong identity. Placing
resolution and the gates at the single launch boundary makes the promise true
for every connector, so support for a new one is a doctrine question rather
than a safety question.

## Canonical fields

### Use cases

#### UC-ACA-1: An unresolved person refuses the invocation

```gherkin
Given an agent session in which no acting person is resolved
When the session invokes a connector
Then the invocation is refused before the connector runs
And the refusal states that no acting person was resolved
And no credential or connection state is created or modified anywhere
```

#### UC-ACA-2: Connector state stays inside the acting person's own store

```gherkin
Given an agent session acting as a resolved person
When the session invokes a connector that reads or writes credential or connection state
Then that state is read and written only within that person's own store
And no state is left in a shared or default location
And another person's stored state is unchanged
```

#### UC-ACA-3: An unattended send is refused however it is expressed

```gherkin
Given an unattended run acting as a resolved person
When the session invokes a connector operation that would cause mail to leave — whether through the connector's own send, reply, or forward operation or through a generic pass-through request that reaches one of those endpoints
Then the invocation is refused before the connector runs
And the refusal states that sending is not available in an unattended run
And no mail leaves
```

#### UC-ACA-4: A settings change is refused on every path and in every run

```gherkin
Given an agent session acting as a resolved person, whether the run is attended or unattended
When the session invokes a connector operation that would change account settings — whether through the connector's own settings operation or through a generic pass-through request that reaches a settings endpoint
Then the invocation is refused before the connector runs
And the refusal states that settings operations are unavailable
And the account's settings are unchanged
```

#### UC-ACA-5: An unclassifiable invocation is refused rather than attempted

```gherkin
Given an agent session acting as a resolved person
When the session invokes a connector operation whose effect cannot be established as permitted
Then the invocation is refused before the connector runs
And the refusal states that the invocation could not be established as permitted
```

#### UC-ACA-6: A connector named directly still reaches the mediated launch

```gherkin
Given an agent session
When the session invokes a connector by its bare command name
Then the mediated launch handles the invocation
And the gates that launch enforces apply to it
```

#### UC-ACA-7: An instructed send is carried out

```gherkin
Given an attended session acting as a resolved person
And the person has asked for a message to be sent
When the session invokes the connector's send operation
Then the send executes from that person's own store
And the message leaves
```

#### UC-ACA-8: One person's stored credentials are unreadable by another's invocation

```gherkin
Given two people whose assistants both operate on the same machine
When an agent session acting as one of them invokes a connector
Then that invocation cannot read the other person's stored credentials
```

## Known caveats

- Whether a run is attended is established from the platform's own session
  context; where it cannot be established the run is treated as unattended, so
  the send gate holds.
- Which connector operations exist, and which of them the assistant may use at
  all, is doctrine owned by that connector's personal-domain tool spec. This
  contract governs where the gates run, not which permitted operations an
  assistant should reach for.

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the gates this contract enforces and the mandate rule that decides when a permitted write runs.
- ~/.teleclaude/docs/personal/spec/tools/gog-cli.md — the permitted-invocation doctrine for the Google connector.
- docs/project/spec/feature/agent_runtime/sealed-commit.md — the sibling mediated-tool contract on the same agent tool surface.
