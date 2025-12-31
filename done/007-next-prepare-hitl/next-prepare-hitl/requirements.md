# Requirements: `teleclaude__next_prepare` HITL Support

## Problem Statement

The current `next_prepare` implementation has several issues:

1. **Missing command:** Dispatches `next-roadmap` which doesn't exist
2. **Wrong paradigm:** Designed only for autonomous AI-to-AI dispatch, not interactive human conversations
3. **Wrong phase logic:** Checks `is_in_progress` (`[>]` in roadmap) which belongs only in `next_work` phase
4. **Automatic slug resolution:** Looks up first roadmap item automatically, but this is only appropriate for autonomous `next_work` phase

## Design Principles

1. **`next_prepare` (Phase A)** = Architect work, interactive, explicit
   - No automatic lookups
   - Human-driven or explicit slug required
   - Produces: roadmap entry, `requirements.md`, `implementation-plan.md`

2. **`next_work` (Phase B)** = Builder work, autonomous
   - Automatic slug resolution from roadmap
   - Fully autonomous build/review/fix/finalize cycle

3. **Idempotent:** Tool checks state, returns guidance for remaining work. If process breaks midway, calling again continues where it left off.

4. **No intermediate callbacks in HITL mode:** When human is in the loop, guidance includes ALL remaining work. The AI completes the full prepare phase in one conversation.

5. **Files must be committed:** When checking if artifacts exist, they must be tracked by git (committed), not just exist on disk. This ensures worktrees created for `next_work` will have access to the files.

## New Parameter

**`hitl`** (Human-In-The-Loop)
- Type: `boolean`
- Default: `true`
- Description: "Human-in-the-loop mode. When true (default), returns guidance for the calling AI to work interactively with the user. When false, dispatches to another AI for autonomous collaboration."

The calling AI infers this from context - if talking to a human, use `true`. If the human explicitly wants AI-to-AI collaboration, use `false`.

## Logic Flow

### HITL = true (default)

Return guidance for calling AI to work with user:

| State | Response |
|-------|----------|
| No slug provided | "Read next-prepare.md. Read todos/roadmap.md. Discuss with user, identify or propose slug, write requirements.md and implementation-plan.md." |
| Slug provided, requirements.md missing | "Read next-prepare.md. Preparing: {slug}. Write requirements.md and implementation-plan.md." |
| Slug provided, only implementation-plan.md missing | "Read next-prepare.md. Preparing: {slug}. Write implementation-plan.md." |
| Both exist but not committed | "Read next-prepare.md. Preparing: {slug}. Commit requirements.md and implementation-plan.md." |
| Both exist and committed | "PREPARED: {slug} is ready for work." |

### HITL = false

Dispatch "next-prepare" command to another AI:

| State | Response |
|-------|----------|
| No slug provided | Dispatch "next-prepare" (no args) |
| Any artifacts missing | Dispatch "next-prepare {slug}" |
| Both exist | "PREPARED: {slug} is ready for work." |

## Acceptance Criteria

- [ ] `hitl` parameter added with default `true`
- [ ] `is_in_progress` check removed from `next_prepare`
- [ ] `next-roadmap` dispatch replaced with `next-prepare`
- [ ] Automatic slug resolution removed for HITL=true mode
- [ ] HITL=true returns comprehensive guidance (no "call again" steps)
- [ ] HITL=false dispatches to another AI
- [ ] Files checked for git tracking before returning PREPARED
- [ ] All tests pass
- [ ] Lint passes
