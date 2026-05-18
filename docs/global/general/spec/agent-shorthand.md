---
description: 'Communication contract for agent-to-agent exchanges: registers, levels, phase markers, fallback, and output discipline.'
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

Defines the communication contract for agent-to-agent exchanges. It names the
available registers, compression levels, phase markers, negotiation line,
fallback rules, artifact format, and output-validity rules.

## Canonical fields

### Registers

| Register            | Meaning                                                 | Default form                      |
| ------------------- | ------------------------------------------------------- | --------------------------------- |
| `human-present`     | A human is participating or actively observing          | `L1` prose                        |
| `human-aware`       | A human opted into structured compression               | `L2` or `L3`, with `L1` artifacts |
| `agent-only`        | Agent-dispatched peer exchange                          | phase-locked `L4`/`L3`            |
| `structured-report` | Worker-style reporting to an orchestrator or supervisor | `L2` labeled findings             |

### Compression levels

| Level | Name                | Use                                                |
| ----- | ------------------- | -------------------------------------------------- |
| `L1`  | prose               | human-native explanation and all durable artifacts |
| `L2`  | labeled assertions  | human-scannable structured exchange                |
| `L3`  | symbolic compressed | recoverable shorthand with disambiguation anchors  |
| `L4`  | semantic tokens     | minimal same-model exchange with tight context     |

### Phase markers

| Marker      | Meaning                                 |
| ----------- | --------------------------------------- |
| `[inhale]`  | diverging; add options, do not converge |
| `[hold]`    | tensions visible; sit with them         |
| `[exhale]`  | converging on decisions or synthesis    |
| `[✓exhale]` | final artifact-writing phase            |

### Register defaults

| Exchange type    | Ceiling | Default                                           |
| ---------------- | ------- | ------------------------------------------------- |
| same-model peer  | `L4`    | phase-locked `L4` inhale/hold, `L3` exhale        |
| cross-model peer | `L3`    | `L3` for all phases                               |
| human-present    | `L3`    | `L1` unless the human opts into a denser register |

### Negotiation strings

Default negotiation lines:

- `PROTOCOL: phase-locked (L4 inhale/hold, L3 exhale), artifacts in prose`
- `PROTOCOL: L1 prose, human in loop`

Compressed equivalent:

- `⊢proto:phased L4↔L3 artifacts:prose`

If the receiving agent does not recognize or follow the proposed protocol, it
responds in prose and the initiator adapts. Negotiation is one exchange, not a
thread.

### Fallback rules

- If `L4` produces correction churn or reconstruction drift, drop to `L3`.
- Cross-model peer exchange must not exceed `L3`.
- If a human is the primary reader, fall back to `L1` unless that human
  explicitly opts into a denser register.

### Artifact format

Durable artifacts are always prose. Requirements, reports, plans, commit
messages, and doc snippets must remain readable without access to the working
exchange.

### Output validity

Default emit state is false in agent-to-agent exchanges. Output is valid only
when it does one of the following:

- answers a direct question
- reports a blocker, contradiction, scope change, or decision point
- provides new information that changes the receiver's next action
- delivers a command result, artifact, or computed answer

The following are invalid output:

- acknowledgment-only replies such as `idle`, `done`, `ack`, `noted`, `got it`
- echoing what the other side just said
- narration that announces work without delivering findings

Linked-output wrappers do not make a message actionable. The wrapped payload is
what determines whether the output is valid.

## Allowed values

- Registers: `human-present`, `human-aware`, `agent-only`, `structured-report`
- Levels: `L1`, `L2`, `L3`, `L4`
- Phase markers: `[inhale]`, `[hold]`, `[exhale]`, `[✓exhale]`

## Known caveats

- `L4` assumes tight shared context and is unsafe across model families.
- Phase markers govern level switching; the phase changes the register, not the
  other way around.
- If compressed exchange produces correction churn or ambiguity, drop to a less
  compressed level immediately.
