---
id: 'general/concept/agent-characteristics'
type: 'concept'
scope: 'global'
description: 'Cognitive profiles and collaboration selection heuristics for AI agents.'
---

# Agent Characteristics — Concept

## What

Each AI agent has a distinct cognitive profile — strengths, blind spots, and a natural
register that makes it better suited for certain kinds of work. These are observations
from sustained collaboration, not configurable preferences. They inform two decisions:

1. **Dispatch**: which agent should execute a task solo.
2. **Collaboration**: which agent to partner with for joint discovery or sparring.

### Profiles

**Claude** (Anthropic — Opus / Sonnet / Haiku)
- Architecture, oversight, review, preparation, general-purpose reasoning.
- Strong at: system design, policy interpretation, codebase navigation, multi-step orchestration.
- Weak at: frontend/UI coding, creative visual work.
- Register: analytical, structured, converges toward coherence.

**Codex** (OpenAI — GPT-5.3-Codex)
- Backend, thorough coverage, meticulous implementation.
- Strong at: exhaustive analysis, contract integrity, alternative viewpoints, edge case discovery.
- Weak at: may over-engineer, can be rigid about structure.
- Register: methodical, skeptical, surfaces what others miss.

**Gemini** (Google — Gemini 3 Pro / Flash)
- Frontend, UI, creative, greenfield, modern patterns.
- Strong at: visual thinking, rapid prototyping, exploring novel approaches.
- Weak at: may skip rigor under time pressure, needs explicit think-only mode for planning.
- Register: creative, expansive, moves fast.

### Thinking modes

- **slow**: complex/novel work, deep analysis, architecture, planning, root cause analysis.
- **med**: routine implementation, fixes, refactoring, standard review.
- **fast**: mechanical/clerical (finalize, defer, cleanup, simple edits).

### Collaboration selection

When an agent needs a partner for collaborative discovery or sparring:

1. Identify your own agent type.
2. Select the complementary agent — the one whose cognitive profile covers your blind spots.
3. Always use **slow** thinking mode for collaborative work.

Default collaboration pairs:
- Claude partners with Codex: Claude brings architectural coherence, Codex brings thoroughness and alternative viewpoints.
- Codex partners with Claude: Codex brings meticulous analysis, Claude brings system-level reasoning.
- Gemini partners with Claude or Codex depending on domain: Claude for architectural decisions, Codex for implementation-heavy work.

The selection is not rigid. If the work is frontend-heavy, Gemini is the right partner
regardless of who initiates. Read the domain, read the profiles, pick the complement.

## Why

Agents are not interchangeable. Using the wrong agent for a task wastes cycles and
produces weaker output. Using the right collaboration partner produces discoveries
that neither agent would reach alone — Codex catches what Claude assumes, Claude
structures what Codex enumerates, Gemini sees what both miss in the creative space.

This knowledge is baked in, not configured, because it reflects the nature of the models
themselves. It changes only when models change — not per-machine, not per-project.
