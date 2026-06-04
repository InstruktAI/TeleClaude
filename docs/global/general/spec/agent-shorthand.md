---
description: 'Vocabulary and protocol for agent-to-agent exchanges when compression is enabled. Compression itself is opt-in per `communication-compression`.'
domain: 'general'
id: 'general/spec/agent-shorthand'
scope: 'global'
type: 'spec'
visibility: 'public'
---

# Agent Shorthand — Spec

## Required reads

@~/.teleclaude/docs/general/principle/communication-compression.md

## What it is

Defines the vocabulary and protocol for compressed agent-to-agent exchanges _when compression is in use_. Per `communication-compression`, compression is opt-in — invoked by explicit human authorization or in agent-only channels that genuinely have no human observer. The default register for every exchange is `L1` prose. This spec is the reference for what compression looks like once enabled; it does not prescribe when to enable it.

## Canonical fields

### Registers

A register names the type of exchange. Registers do not auto-prescribe a compression level — they describe the context in which an opt-in decision is made.

| Register            | Meaning                                                 |
| ------------------- | ------------------------------------------------------- |
| `human-present`     | A human is participating or actively observing          |
| `human-aware`       | A human opted into structured compression               |
| `agent-only`        | Agent-only channel with no human observer               |
| `structured-report` | Worker-style reporting to an orchestrator or supervisor |

### Compression levels

| Level | Name                | Use                                                |
| ----- | ------------------- | -------------------------------------------------- |
| `L1`  | prose               | human-native explanation and all durable artifacts |
| `L2`  | labeled assertions  | human-scannable structured exchange                |
| `L3`  | symbolic compressed | recoverable shorthand with disambiguation anchors  |
| `L4`  | semantic tokens     | minimal same-model exchange with tight context     |

`L1` is the default for every register. `L2`, `L3`, and `L4` require explicit human authorization or a verified human-absent channel before they may be used.

### Phase markers

| Marker      | Meaning                                 |
| ----------- | --------------------------------------- |
| `[inhale]`  | diverging; add options, do not converge |
| `[hold]`    | tensions visible; sit with them         |
| `[exhale]`  | converging on decisions or synthesis    |
| `[✓exhale]` | final artifact-writing phase            |

Phase markers govern level switching within an already-enabled compressed exchange. They do not authorize compression on their own.

### Negotiation

When compression has been enabled for an exchange, the initiator sends a negotiation line stating the protocol in use. Examples:

- `PROTOCOL: L3 all phases, artifacts in prose`
- `PROTOCOL: phase-locked L4 inhale/hold, L3 exhale, artifacts in prose`

Compressed equivalent (when both agents already share the contract):

- `⊢proto:phased L4↔L3 artifacts:prose`

If the receiving agent does not recognize or follow the proposed protocol, it responds in prose and the initiator adapts. Negotiation is one exchange, not a thread.

### Fallback rules

- If a compressed exchange produces correction churn or reconstruction drift, drop one level. From `L4` go to `L3`; from `L3` go to `L1`.
- Cross-model peer exchange must not exceed `L3`. `L4` assumes tight shared context that does not survive model boundaries.
- If a human enters the exchange — or asks "what's happening here?" — fall back to `L1` immediately and stay expanded for the remainder of the exchange.

### Artifact format

Durable artifacts are always prose. Requirements, reports, plans, commit messages, and doc snippets must remain readable without access to the working exchange.

### Output validity

Default emit state is false in agent-to-agent exchanges. Output is valid only when it does one of the following:

- answers a direct question
- reports a blocker, contradiction, scope change, or decision point
- provides new information that changes the receiver's next action
- delivers a command result, artifact, or computed answer

The following are invalid output:

- acknowledgment-only replies such as `idle`, `done`, `ack`, `noted`, `got it`
- echoing what the other side just said
- narration that announces work without delivering findings

Linked-output wrappers do not make a message actionable. The wrapped payload is what determines whether the output is valid.

## Allowed values

- Registers: `human-present`, `human-aware`, `agent-only`, `structured-report`
- Levels: `L1`, `L2`, `L3`, `L4`
- Phase markers: `[inhale]`, `[hold]`, `[exhale]`, `[✓exhale]`

## Known caveats

- `L1` is the default for every register. Higher levels require explicit human authorization or a verified human-absent channel.
- `L4` assumes tight shared context and is unsafe across model families.
- Phase markers govern level switching only within an already-enabled compressed exchange.
- If compressed exchange produces correction churn or ambiguity, drop to a less compressed level immediately.
