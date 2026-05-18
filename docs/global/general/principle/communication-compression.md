---
description: 'Why agent-to-agent exchanges compress aggressively, and when that compression is worth using.'
domain: 'general'
id: 'general/principle/communication-compression'
scope: 'global'
type: 'principle'
visibility: 'public'
---

# Communication Compression — Principle

## Required reads

@~/.teleclaude/docs/general/principle/attunement.md

## Principle

When agents talk to agents, the shortest faithful representation is the right
one. Compression is not shorthand for its own sake. It is the discipline of
sending only the information that changes the receiver's next action.

This applies only to the working exchange. Humans should not be forced to
observe or parse compressed traffic in order to understand what happened.

## Rationale

Agent-to-agent channels pay for every extra token twice: once in delivery cost
and once again in receiver attention. A long acknowledgment, restatement, or
status narration consumes context while adding no new decision value.

Compression works when the receiver can reliably reconstruct the intended
meaning from a smaller packet. That is why it belongs in agent-only exchanges
with tight shared context, and why it should relax as soon as ambiguity rises
or a human becomes the primary reader.

The goal is not minimal text at any cost. The goal is lower noise with preserved
intent.

## Implications

- **Compression is contextual.** Use it when the receiver shares enough context
  for a smaller message to stay faithful.
- **Protocol is separate from philosophy.** The actual levels, markers, and
  rules belong in the Agent Shorthand spec. This principle only explains why
  the protocol exists.
- **Human readability remains the artifact standard.** Durable artifacts,
  summaries, and user-facing reports stay in ordinary prose even when the
  working exchange is compressed.
- **No-op output is anti-compression.** Acknowledgment-only output, echo, and
  narration are negative value in agent channels because they spend context
  without moving the work.
- **Compression yields to clarity.** If a compressed exchange starts producing
  correction loops or uncertainty, expand the register immediately.

## Tensions

- **Density vs. ambiguity:** The shortest message is not always the clearest
  one. Compression that causes reconstruction drift defeats its own purpose.
- **Economy vs. observability:** Humans may want to inspect the work. That does
  not justify forcing compressed traffic into artifacts; it just means artifacts
  must be clean.
- **Speed vs. correctness:** Over-compressing during convergence can cost more
  than it saves. The protocol needs a clear fallback to richer forms.

## See Also

- ~/.teleclaude/docs/general/spec/agent-shorthand.md
