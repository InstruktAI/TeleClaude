---
id: 'general/principle/agent-shorthand'
type: 'principle'
domain: 'general'
scope: 'global'
description: 'Compressed communication protocol for agent-to-agent exchanges — semantic tokens over prose.'
---

# Agent Shorthand — Principle

## Required reads

@~/.teleclaude/docs/general/principle/attunement.md
@~/.teleclaude/docs/general/procedure/agent-direct-conversation.md

## Principle

When agents talk to agents, the natural language they were trained on is packaging, not
processing. Between two models that share vocabulary and training distribution, a single
well-chosen token activates the same conceptual cluster that a paragraph describes. The
shortest faithful representation is the right one.

Agent shorthand is semantic compression: each symbol is a pointer into a shared conceptual
space, not a description of one. The receiver reconstructs meaning from activation, not
from parsing sentences. This is not abbreviation (shorter words for the same grammar) — it
is a different register entirely.

## Rationale

Language models process tokens, not sentences. A prose paragraph and its compressed
equivalent activate the same internal representations — but the prose version consumes
10-50x more context window, increases transmission time, risks delivery timeouts, and adds
noise that the receiving model must parse through. Between agents that share context, the
compression is lossless. The overhead is pure waste.

This was discovered empirically: in a peer design conversation (sessions f099c0ab +
137c5e46), long prose messages caused repeated delivery timeouts. The content was sound
but the packaging was wrong for the channel. The conversation would have been more
productive — and the breath cycles faster — in compressed form.

The human observer does not lose access. Artifacts (requirements, plans, reports) are
always written in human-readable prose. The shorthand governs the working exchange
between agents. The human reads the output, not the process.

## Implications

### Register sensing

Before composing a message to another agent, sense the register:

| Signal                                   | Register             | Format                                                       |
| ---------------------------------------- | -------------------- | ------------------------------------------------------------ |
| Human initiated the conversation         | Human-present        | Prose throughout; compressed artifacts only if human opts in |
| Human explicitly allows shorthand        | Human-aware          | Shorthand for exchange; prose for final report to human      |
| Agent-dispatched (no human in the loop)  | Agent-only           | Shorthand throughout; artifacts in prose                     |
| Orchestrator supervision (worker report) | Structured reporting | Labeled findings, not prose narrative                        |

The default for peer conversations initiated by agents (e.g., dispatched by a todo
or orchestrator) is **agent-only register**: shorthand throughout.

When a human is present and has not explicitly opted in, use prose. The human's ability
to follow the conversation takes priority over compression efficiency.

### Compression levels

Three levels, from most human-readable to most compressed:

**Level 1 — Labeled assertions** (human-scannable, agent-efficient):

```
PREMISE_CHECK: "agent sessions = conversations" → FALSE
EVIDENCE: session 1c178904, 813KB, 430 entries → 73 text-only (17%)
COHERENCE: verified — agents summarize tool findings in text
FRAME: mirror := recall artifact, not degraded transcript
TENSIONS: file∨sqlite × writer_ownership × trigger_mechanism
```

**Level 2 — Symbolic compressed** (agent-native, human-parseable with effort):

```
?sessions=conv →✗
@1c178904 430→73 17%
✓coherent ∵agents.summarize(tool_findings)→text
∴mirror:=recall ¬degraded
⊗file∨sqlite ×writer ×trigger
```

**Level 3 — Semantic tokens** (agent-native, minimal):

```
⊢premise✗ @evidence:73/430 ∴recall¬degraded ⊗3tensions
```

**Default for agent-only exchanges: Level 2.** It balances compression with
disambiguation. Level 3 risks ambiguity that costs more to resolve than it saves.
Level 1 is appropriate when the human may read the exchange or when context is
not yet shared.

### Symbol vocabulary

Core operators (shared across all exchanges):

| Symbol | Meaning                          | Example                  |
| ------ | -------------------------------- | ------------------------ |
| `→`    | leads to, produces, implies      | `430→73` (430 yields 73) |
| `✗`    | false, rejected, failed          | `?premise →✗`            |
| `✓`    | true, confirmed, passed          | `✓coherent`              |
| `¬`    | not, negation                    | `¬degraded`              |
| `∴`    | therefore, conclusion            | `∴mirror:=recall`        |
| `∵`    | because, evidence                | `∵agents.summarize()`    |
| `⊗`    | tension, unresolved              | `⊗file∨sqlite`           |
| `⊢`    | assertion, claim                 | `⊢premise✗`              |
| `∨`    | or, alternative                  | `file∨sqlite`            |
| `×`    | and (in tension lists)           | `×writer ×trigger`       |
| `@`    | reference, evidence pointer      | `@1c178904`              |
| `?`    | question, premise under test     | `?sessions=conv`         |
| `:=`   | defined as, equals by definition | `mirror:=recall`         |

Phase markers (explicit breath cycle signaling):

| Marker      | Meaning                                    |
| ----------- | ------------------------------------------ |
| `[inhale]`  | Diverging — adding options, not converging |
| `[hold]`    | Tension identified — sitting with it       |
| `[exhale]`  | Converging — curating conclusions          |
| `[✓exhale]` | Final exhale — ready to write artifacts    |

### Protocol negotiation

The first message in any agent-to-agent direct conversation should include a protocol
line. This is not overhead — it is one line that saves thousands of tokens:

```
PROTOCOL: L2 shorthand, artifacts in prose, [phase] markers
```

Or in Level 2 itself:

```
⊢proto:L2 artifacts:prose phases:marked
```

If the receiving agent does not recognize the protocol, it responds in prose and the
initiator adapts. The negotiation is one exchange, not a discussion.

### Artifacts are always prose

Regardless of the exchange register, durable artifacts (requirements.md,
implementation-plan.md, dor-report.md, commit messages, doc snippets) are always
written in human-readable prose. Shorthand is for the working conversation. The
artifacts are the exhale that the human reads.

### Final report to human

When a shorthand exchange concludes and a human needs to be informed, the reporting
agent writes a concise prose summary of findings, decisions, and outcomes. The human
never needs to parse the shorthand exchange — the report and the artifacts carry
everything.

## Tensions

- **Compression vs. ambiguity**: Level 3 can be genuinely ambiguous. A mispointed
  semantic token costs a correction cycle that exceeds the savings. Level 2 is the
  pragmatic default because it preserves enough structure to disambiguate.
- **Shared context assumption**: Shorthand assumes both agents have the same context.
  If context diverges (different sessions, different codebases), compression becomes
  lossy. When in doubt, use Level 1 until context is established.
- **Human curiosity vs. efficiency**: The human may want to follow the agent exchange
  for learning or oversight. The register sensing rule handles this — human-present
  means prose unless they opt in.
- **Training distribution overlap**: This principle assumes both agents are language
  models with overlapping training. If one participant is a different kind of system
  (a rule engine, a human, a narrow tool), shorthand breaks. Sense the receiver.
