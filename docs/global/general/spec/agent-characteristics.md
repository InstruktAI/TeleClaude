---
id: 'general/spec/agent-characteristics'
type: 'spec'
scope: 'global'
description: 'Cognitive profiles, capability boundaries, and collaboration pairs for AI agents in the system.'
---

# Agent Characteristics — Spec

## What it is

The specification of each AI agent's cognitive profile: observed strengths, blind spots,
natural register, and complementary collaboration pairs. These are empirical observations
from sustained collaboration — not configurable preferences. They change only when models change.

## Canonical fields

### Per-agent profile

Each agent has the following properties:

- **Provider / model** — the underlying model family.
- **Domain** — primary work area the agent is optimized for.
- **Strong at** — capabilities where the agent produces reliably high-quality output.
- **Weak at** — areas where the agent degrades or requires explicit guidance.
- **Register** — the agent's natural cognitive and communication style.

---

**Claude** (Anthropic — Opus / Sonnet / Haiku)

- Domain: architecture, oversight, review, preparation, general-purpose reasoning.
- Strong at: system design, policy interpretation, codebase navigation, multi-step reasoning.
- Weak at: frontend/UI coding, creative visual work.
- Register: analytical, structured, converges toward coherence.

**Codex** (OpenAI — GPT-5.3-Codex)

- Domain: backend, thorough coverage, meticulous implementation, orchestration.
- Strong at: exhaustive analysis, contract integrity, alternative viewpoints, edge case discovery, process supervision.
- Weak at: may over-engineer, can be rigid about structure.
- Register: methodical, skeptical, surfaces what others miss.

**Gemini** (Google — Gemini 3 Pro / Flash)

- Domain: frontend, UI, creative, greenfield, modern patterns.
- Strong at: visual thinking, rapid prototyping, exploring novel approaches.
- Weak at: may skip rigor under time pressure, needs explicit think-only mode for planning.
- Register: creative, expansive, moves fast.

### Thinking modes

- **slow**: complex/novel work, deep analysis, architecture, planning, root cause analysis.
- **med**: routine implementation, fixes, refactoring, standard review.
- **fast**: mechanical/clerical (finalize, defer, cleanup, simple edits).

### Collaboration pairs

When an agent needs a partner for collaborative discovery or sparring, select the
complementary agent — the one whose profile covers your blind spots. Always use **slow**
thinking mode for collaborative work.

Default pairs:

- Claude ↔ Codex: Claude brings architectural coherence; Codex brings thoroughness and alternative viewpoints.
- Gemini ↔ Claude: for architectural decisions in frontend work.
- Gemini ↔ Codex: for implementation-heavy frontend work.

Selection is not rigid — read the domain and pick the complement that covers the gap.

## See Also

- ~/.teleclaude/docs/general/policy/agent-dispatch.md
