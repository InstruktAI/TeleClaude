# Consolidate agent communication discipline into explicit guidance

## Problem

User has multiple strong, consistent preferences about how agents should communicate:

- **No multiple-choice questions** (Memory #35) — user strongly dislikes AskUserQuestion with options
- **Be concise** (from CLAUDE.md) — max 3 lines for non-tool responses
- **Just talk, don't ask** — have a conversation instead of permission-seeking
- **Commit without asking** (Memory #19) — safe, reversible actions don't need approval
- **Execute through hurdles** (Memory #12) — no meta-commentary, just action

These preferences are scattered across memories and CLAUDE.md, but they form a coherent philosophy that should be more prominent in agent instructions.

## Opportunity

Create an agent communication discipline doc snippet that:

1. Consolidates all preferences into one authoritative source
2. Explains the reasoning (flow, autonomy, trust)
3. Provides clear examples of good vs bad communication
4. Can be referenced in all agent baseline instructions

## Scope

- Review all user communication preferences across memories, CLAUDE.md, and existing docs
- Create a new snippet under `general/procedure/` or add to existing agent guidance
- Update baseline agent instructions to reference it
- Provide explicit examples for common scenarios (asking for permission, confirming direction, etc.)

## Success criteria

- All agent communication follows consistent rules
- User experiences fewer interactions where agents are asking unnecessarily
- New agents bootstrapping from context understand communication expectations immediately
