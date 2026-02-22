# Requirements: consolidate-methodology-skills

## Goal

Consolidate 6 methodology skills from Claude Code plugins (superpowers, frontend-design) into `agents/skills/` so that all agent runtimes (Claude, Gemini, Codex) receive the same process disciplines via `telec sync`.

## Scope

### In scope:

1. **systematic-debugging** — 4-phase root cause methodology (reproduce, bisect, isolate, fix). Source: superpowers plugin.
2. **test-driven-development** — RED-GREEN-REFACTOR with iron laws and rationalizations table. Source: superpowers plugin.
3. **verification-before-completion** — Evidence-before-claims gate function. Source: superpowers plugin.
4. **brainstorming** — Socratic design refinement with hard gate before implementation. Source: superpowers plugin.
5. **receiving-code-review** — Technical rigor over performative agreement when handling review feedback. Source: superpowers plugin.
6. **frontend-design** — Distinctive UI creation methodology (typography, motion, spatial composition). Source: frontend-design plugin.

Each skill:

- Authored as `agents/skills/{name}/SKILL.md` following the TeleClaude artifact schema.
- Content adapted from source material to be agent-agnostic (no Claude-specific tool references).
- Validated and distributed via `telec sync`.

### Out of scope:

- Modifying existing TeleClaude commands to reference the new skills (follow-up work).
- Removing or replacing the superpowers/frontend-design plugins from Claude Code.
- Consolidating framework-specific skills (nextjs-\*, shopify, astro-webapp, etc.).
- Consolidating skills that overlap with existing TeleClaude pipeline (writing-plans, executing-plans, etc.).
- Changes to the distribute.py compiler or artifact schema.

## Success Criteria

- [ ] 6 new `agents/skills/{name}/SKILL.md` files exist and follow artifact schema.
- [ ] `telec sync` passes validation with no errors.
- [ ] Each skill is distributed to `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`.
- [ ] Content is agent-agnostic: no references to Claude-specific plugins, tools, or plugin loading mechanisms.
- [ ] Core thinking disciplines are preserved: the methodology substance is equivalent to or better than the source material.

## Constraints

- Follow the artifact schema from `general/spec/agent-artifacts`: frontmatter (`name`, `description`), body sections (`# Title`, `## Purpose`, `## Scope`, `## Inputs`, `## Outputs`, `## Procedure`).
- Do not copy source material verbatim — adapt to our schema while preserving the methodology's substance and rigor.
- Skills must not assume any specific runtime's tool set. They describe thinking processes, not tool invocations.
- No new Python code or tests required — this is purely artifact authoring work.

## Risks

- Content adaptation could water down the methodology's rigor. Mitigation: preserve the core discipline tables, iron laws, and gate functions even if restructured.
- Naming collision with existing superpowers plugin skills on Claude. Mitigation: after consolidation, the native `agents/skills/` versions take precedence in the TeleClaude distribution path; the plugin versions remain as fallback.
