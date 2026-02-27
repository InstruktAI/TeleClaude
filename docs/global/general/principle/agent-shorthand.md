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

| Signal                                   | Register             | Format                                          |
| ---------------------------------------- | -------------------- | ----------------------------------------------- |
| Human initiated the conversation         | Human-present        | L1 prose; ask the human what level they prefer  |
| Human opts in to labeled format          | Human-aware (L2)     | L2 exchange; L1 prose for final report to human |
| Human opts in to shorthand               | Human-aware (L3)     | L3 exchange; L1 prose for final report to human |
| Agent-dispatched, same model             | Agent-only           | Phase-locked L4/L3; artifacts in L1 prose       |
| Agent-dispatched, cross-model            | Agent-only           | L3 all phases; artifacts in L1 prose            |
| Orchestrator supervision (worker report) | Structured reporting | L2 labeled findings, not prose narrative        |

The default for peer conversations initiated by agents (e.g., dispatched by a todo
or orchestrator) is **agent-only register**: phase-locked L4/L3 throughout.

When a human is present, default to L1 prose and ask what level they prefer. Power
users may prefer L2 (labeled assertions) for observability without sacrificing scan
speed. The human's stated preference takes priority over compression efficiency.

### Compression levels

Four levels, from human-native to agent-native:

**Level 1 — Prose** (human-native):

```
The premise that agent sessions equal conversations is false. Session 1c178904
contains 813KB across 430 entries, but only 73 (17%) are actual text — the rest
are tool use. Agents summarize tool findings in their text responses, which means
the mirror should be a recall artifact, not a degraded transcript. Three tensions
remain unresolved: file vs sqlite storage, writer ownership, and trigger mechanism.
```

**Level 2 — Labeled assertions** (human-scannable, agent-efficient):

```
PREMISE_CHECK: "agent sessions = conversations" → FALSE
EVIDENCE: session 1c178904, 813KB, 430 entries → 73 text-only (17%)
COHERENCE: verified — agents summarize tool findings in text
FRAME: mirror := recall artifact, not degraded transcript
TENSIONS: file∨sqlite × writer_ownership × trigger_mechanism
```

**Level 3 — Symbolic compressed** (recoverable shorthand, agent-native):

```
?sessions=conv →✗
@1c178904 430→73 17%
✓coherent ∵agents.summarize(tool_findings)→text
∴mirror:=recall ¬degraded
⊗file∨sqlite ×writer ×trigger
```

**Level 4 — Semantic tokens** (context-inferred, minimal):

```
⊢premise✗ @evidence:73/430 ∴recall¬degraded ⊗3tensions
```

The key distinction between L3 and L4: L3 preserves disambiguation anchors (`:=`,
parenthetical clarifiers, causal chains with `∵`). L4 drops them — the receiver
reconstructs from shared context alone. L3 is recoverable from the message itself.
L4 requires the shared context to be intact.

**Default for same-model exchanges: phase-locked switching.** The breath cycle
determines which level to use:

| Phase       | Level | Why                                                                 |
| ----------- | ----- | ------------------------------------------------------------------- |
| `[inhale]`  | L4    | Divergence is the goal. Ambiguity is tolerable. Speed matters.      |
| `[hold]`    | L4    | Naming tensions, not resolving them. Density helps.                 |
| `[exhale]`  | L3    | Converging on decisions. Disambiguation prevents wrong commitments. |
| `[✓exhale]` | L1/L2 | Writing artifacts. Humans read these. Clarity is non-negotiable.    |

**Cross-model exchanges: L3 is the ceiling.** L4 semantic tokens rely on shared
training distribution — the same token activating the same conceptual cluster in
both sender and receiver. Between different model families (Claude + Gemini,
Claude + Codex), training distributions overlap but are not identical. An L4
pointer might land in a slightly different neighborhood in the receiver's
activation space, and neither model would detect the drift. L3 is safe across
model boundaries because the disambiguation anchors (`:=`, `∵`, parenthetical
clarifiers) make the message self-contained — the receiver parses structure, not
activation. The symbolic grammar is math and logic notation, universal across any
model that can process structured text.

| Exchange type    | Ceiling | Phase-locked range        |
| ---------------- | ------- | ------------------------- |
| Same-model peer  | L4      | L4 inhale/hold, L3 exhale |
| Cross-model peer | L3      | L3 all phases             |

Phase markers are the switching signal. When you emit `[exhale]`, you shift to L3.
When you emit `[inhale]`, you shift to L4. The level follows the phase, not the other
way around.

**Fallback policy:** If L4 exchanges produce repeated correction cycles or
reconstruction divergence, drop to L3 as the floor for all phases. L3 is always
safe — it carries its own disambiguation. L4 is the aspiration — when shared context
is tight and delivery is reliable, it is the most efficient register. When it creates
noise, retreat without hesitation.

Level 2 is appropriate when a human may read the exchange. Level 1 is the default
when a human is actively in the conversation.

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

### Level 4 — divergence risk and mitigation

Level 4 tokens are pointers, not descriptions. A single token like `⊗latency` can
activate multiple conceptual clusters in the receiver: network latency, query latency,
user-perceived latency. At L3, `⊗latency(remote_api_call)` disambiguates with a
parenthetical anchor. At L4, the anchor is dropped — the receiver reconstructs from
shared context alone.

The risk is **silent divergence**: both agents proceed confidently with slightly
different reconstructions of the same L4 exchange. The divergence is invisible until
artifacts conflict. A correction cycle at that point costs more than L3 would have
cost from the start.

Mitigations:

- **Phase-locked switching** is the primary defense. L4 during inhale/hold is safe
  because ambiguity during exploration has low cost. The L3 exhale is the sync point
  — both agents verify alignment before committing to action.
- **Tight shared context** makes L4 safe. When both agents have read the same files,
  same conversation, same artifacts, the pointers have one valid target. Cold starts
  (one agent hasn't seen what the other has) make L4 lossy — use L3 until context
  is established.
- **Short bursts** over **long exchanges**. L4 works best in 1-3 line exchanges
  between agents that just read the same codebase together. Over many L4 turns,
  small reconstruction differences accumulate.

### Protocol negotiation

The first message in any agent-to-agent direct conversation should include a protocol
line. This is not overhead — it is one line that saves thousands of tokens:

```
PROTOCOL: phase-locked (L4 inhale/hold, L3 exhale), artifacts in prose
```

Or in Level 3 itself:

```
⊢proto:phased L4↔L3 artifacts:prose
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

- **Compression vs. ambiguity**: Level 4 can be genuinely ambiguous. A mispointed
  semantic token during convergence costs a correction cycle that exceeds the savings.
  Phase-locked switching resolves this: L4 during exploration (where ambiguity is
  cheap), L3 during convergence (where disambiguation matters). If L4 creates repeated
  correction cycles, drop to L3 as the floor — the fallback is always available.
- **Shared context assumption**: Shorthand assumes both agents have the same context.
  If context diverges (different sessions, different codebases), compression becomes
  lossy. When in doubt, use L2 until context is established.
- **Human curiosity vs. efficiency**: The human may want to follow the agent exchange
  for learning or oversight. The register sensing rule handles this — human-present
  means prose unless they opt in. Power users may prefer L2 (labeled assertions) for
  observability; the protocol negotiation accommodates this preference.
- **Training distribution overlap**: L4 assumes both agents share training distribution
  — same model family, same conceptual neighborhoods. Between different model families
  (Claude ↔ Gemini, Claude ↔ Codex), L4 pointers may activate slightly different
  clusters with no correction signal. L3 is the cross-model ceiling because its
  disambiguation anchors make messages self-contained regardless of the receiver's
  training. If one participant is a different kind of system entirely (a rule engine,
  a human, a narrow tool), shorthand breaks. Sense the receiver.
