# Consolidate AI Agent Discipline Guidance — Idea

**Status:** Actionable Finding
**Memory Sources:** IDs 19, 25, 35, 36
**Created:** 2026-02-19

## Problem

AI agent behavioral expectations are scattered across 4 separate memories:

- **ID 19:** Checkpoint commit without asking (autonomy friction)
- **ID 25:** Always restart daemon after code changes (validation friction)
- **ID 35:** No multiple choice questions (communication preference)
- **ID 36:** Git stash policy + concise recommendations (decision + preference)

Each memory describes a piece of the discipline, but collectively they form a pattern: **agents are too cautious and over-communicate when they should be autonomous and decisive.**

## Insight

The friction is not isolated incidents—it's a recurring pattern in how agents approach decisions. The CLAUDE.md autonomy policy exists but isn't strong enough in practice. Agents need a single, cohesive "Agent Discipline" guide that unifies these principles and gives clear, actionable rules.

## Recommendation

Create a new doc snippet (`general/procedure/agent-discipline`) that:

1. Consolidates the 4 scattered principles into one coherent guide
2. Provides clear decision trees for common scenarios (commit? ask? restart?)
3. Links back to autonomy policy but translates it into agent-specific behaviors
4. Include examples of anti-patterns (asking permission, over-explaining, etc.)

This would reduce future friction and give new agents a single source of truth for behavioral expectations.

## Follow-up

- If created, update existing memory IDs 19, 25, 35, 36 to link to the new doc instead of standing alone
- Consider adding pre-commit hooks or linting rules to enforce some of these behaviors automatically
