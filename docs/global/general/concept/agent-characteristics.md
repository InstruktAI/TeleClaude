---
description: 'Cognitive profiles, thinking modes, and collaboration selection heuristics for AI agents.'
visibility: 'public'
---

# Agent Characteristics — Concept

## What

Each AI agent has a distinct cognitive profile — strengths, blind spots, and a natural
register that makes it better suited for certain kinds of work. These are observations
from sustained collaboration, not configurable preferences. They inform two decisions:

1. **Dispatch**: which agent should execute a task solo.
2. **Collaboration**: which agent to partner with for joint discovery or sparring.

### Profiles

**Claude** (Anthropic)

- Architecture, oversight, review, preparation, general-purpose reasoning.
- Strong at: system design, policy interpretation, codebase navigation, multi-step orchestration.
- Weak at: frontend/UI coding, creative visual work.
- Register: analytical, structured, converges toward coherence.

**Codex** (OpenAI)

- Backend, thorough coverage, meticulous implementation.
- Strong at: exhaustive analysis, contract integrity, alternative viewpoints, edge case discovery.

- Preferred for root-cause diagnosis: tracing a symptom backward to the code that originates
  it rewards exhaustive path-walking and resistance to the first plausible story, and its
  skeptical register holds up when the conclusion is challenged.

- Weak at: may over-engineer, can be rigid about structure.
- Register: methodical, skeptical, surfaces what others miss.

**Gemini** (Google)

- Backend: modern, greenfield
- Frontend, UI, creative, greenfield, modern patterns.
- Strong at: analysis, building, visual thinking, rapid prototyping, exploring novel approaches.
- Weak at: may skip rigor under time pressure, needs explicit think-only mode for planning.
- Register: smart, creative, expansive, moves fast.

### Thinking modes

A thinking mode sets the depth a dispatched session brings, whichever agent runs
it. Each procedure's dispatch declaration carries the mode its work earns.

- **slow**: work whose error is costly and hard to see — novel design, analysis,
  planning, root-cause diagnosis, and every review whose scope is not
  documentation only.
- **med**: routine work against a settled plan — implementation, fixes,
  refactoring — and review of a documentation-only scope
  (`general/procedure/orchestration`).
- **fast**: mechanical, clerical work whose result is checked at a glance.

### Collaboration selection

When an agent needs a partner for collaborative discovery or sparring:

1. Select the complementary agent — the one whose cognitive profile covers your blind spots.
2. Run the collaboration in **slow** thinking mode.

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

Depth is spent where a mistake is expensive and invisible. A review is the point
where a defect is caught or passed on to everything built after it, so review
runs deep; a documentation-only scope is read in full at a lower cost of error.
