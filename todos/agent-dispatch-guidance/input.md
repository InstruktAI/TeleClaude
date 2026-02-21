# Input: agent-dispatch-guidance

## Problem

The next-machine uses hardcoded Python matrices (`WORK_FALLBACK`, `PREPARE_FALLBACK`) to select which agent runs each phase. This is rigid (no domain awareness), unmaintainable, and the wrong model — the orchestrator AI can infer domain from the work item and should choose.

## Solution

Replace deterministic agent selection with composed guidance text. The next-machine stops picking agents. Instead, it embeds a guidance block in the dispatch instructions. The orchestrator reads the work item, reads the guidance, and selects agent + thinking mode itself.

Agent availability and strengths are declared in `config.yml` (per-machine application config). Three fields per agent: `enabled`, `strengths`, `avoid`.

## Agent Strengths (User-Defined)

- **Claude**: architecture, oversight, review, preparation, general-purpose. Avoid: frontend/UI coding, creative visual work.
- **Gemini**: frontend, UI, creative, greenfield, modern patterns. The artist.
- **Codex**: backend, thorough coverage, meticulous implementation.

## Thinking Mode

Also moves from hardcoded to guidance. The orchestrator assesses complexity:

- slow: complex/novel work, deep analysis, thorough review
- med: routine implementation, fixes, standard tasks
- fast: mechanical/clerical (finalize, defer, cleanup)

## Key Design Decisions

1. Domain inference is AI's job — no metadata field on roadmap entries
2. Agent availability is config-driven (`config.yml`), not binary-detection
3. Binary paths remain constants in `AGENT_PROTOCOL` — not configurable
4. Runtime degradation (rate limits) stays in DB via `mark_agent_status`
5. `format_tool_call` loses `agent`/`thinking_mode` params, gains `guidance`

## Design Doc

See `docs/plans/2026-02-21-agent-dispatch-guidance-design.md`

## Implementation Plan

See `docs/plans/2026-02-21-agent-dispatch-guidance-plan.md`
