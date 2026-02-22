# Consolidate Methodology Skills for Cross-Agent Distribution

## Problem

Claude Code has methodology skills (via the superpowers plugin and frontend-design plugin) that provide process discipline — debugging methodology, TDD, verification gates, brainstorming, code review rigor, and creative frontend design. These are loaded exclusively into Claude via the plugin system. When TeleClaude dispatches Gemini or Codex as workers, they receive none of these disciplines. A Gemini worker doing a bug fix has no debugging methodology. A Codex worker writing code has no TDD discipline.

## Desired Outcome

6 methodology skills consolidated into `agents/skills/` in the TeleClaude artifact format, distributed to all three runtimes (Claude, Gemini, Codex) via `telec sync`.

## Skills to Consolidate

### Tier 1: Core Process Methodology (5 skills)

1. **systematic-debugging** — 4-phase root cause methodology: reproduce, bisect, isolate, fix. Source: `superpowers` plugin. ~297 lines. Any agent doing bug fixes needs this. The `bug-delivery-service` fix worker (`next-bugs-fix`) directly needs this.

2. **test-driven-development** — RED-GREEN-REFACTOR with iron laws and rationalizations table. Source: `superpowers` plugin. ~371 lines. Any agent writing code produces better output under TDD discipline.

3. **verification-before-completion** — Evidence before claims gate function + common failures table. Source: `superpowers` plugin. ~140 lines. Prevents premature "done" declarations from any agent.

4. **brainstorming** — Socratic design refinement with hard gate. Source: `superpowers` plugin. ~97 lines. Pre-implementation thinking discipline for creative work.

5. **receiving-code-review** — Technical rigor over performative agreement. Source: `superpowers` plugin. ~214 lines. Critical for review fix workers that receive findings.

### Tier 2: Creative Capability (1 skill)

6. **frontend-design** — Distinctive UI creation methodology — bold aesthetics, typography, motion, spatial composition. Source: `frontend-design` plugin. ~42 lines. Prevents "generic AI slop" interfaces. Specifically wanted for Gemini creative/graphical work.

## Source Locations

- Superpowers: `~/.claude/plugins/cache/claude-plugins-official/superpowers/4.3.0/skills/`
- Frontend-design: `~/.claude/plugins/cache/claude-plugins-official/frontend-design/236752ad9ab3/skills/`

## Constraints

- Content must be agent-agnostic: no Claude-specific tool references, no plugin system assumptions.
- Must follow TeleClaude artifact schema: frontmatter (`name`, `description`), then `# Title`, `## Required reads`, `## Purpose`, `## Scope`, `## Inputs`, `## Outputs`, `## Procedure`.
- Skills don't take arguments — they provide methodology from conversation context.
- Adapt content to our format, don't just copy verbatim. Preserve the thinking discipline; restructure to fit our schema.
- Run `telec sync` after creation to validate and distribute.

## What NOT to Consolidate (and why)

- writing-plans, executing-plans: Covered by `next-prepare-draft` / `next-build`
- requesting-code-review: Covered by `next-review` pipeline
- dispatching-parallel-agents, subagent-driven-development: Covered by TeleClaude teams
- using-git-worktrees: Already exists as `worktree-manager-skill`
- finishing-a-development-branch: Covered by `next-finalize`
- using-superpowers, writing-skills: Meta skills for Claude plugin authoring
- feature-dev (command + agents): Entire workflow duplicates prepare/build/review/finalize
- Framework skills (nextjs-\*, shopify, etc.): Project-level, not global methodology

## Composability Note

Skills can reference other skills. The `research` skill composes with `youtube`. The `next-build` command references `superpowers:systematic-debugging`. After consolidation, commands can reference these skills natively (e.g., `systematic-debugging` instead of `superpowers:systematic-debugging`), making them available to all agents, not just Claude.
