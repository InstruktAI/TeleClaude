---
description: 'Judgment of free-text content belongs to intelligence, not to code that grades it. The impulse to build a validator is the warning sign.'
visibility: 'public'
---

# Intelligence Boundaries — Principle

## Principle

When the question is "is this content meaningful, important, complete, on-topic, or correct?", the answer comes from intelligence — the agent reading it — not from code that grades it. Code that classifies, scores, judges, evaluates, or auto-edits free-text content substitutes automation for judgment, and the substitution decays.

## Rationale

Heuristics built on regex, word counts, or hardcoded vocabulary are correct only against today's language. They go wrong silently when anything shifts. Auto-editors are worse: they rewrite the agent's intent to satisfy their own grading. Once a rubric exists in code, agents learn to write to the rubric — the rubric becomes the artifact and the artifact becomes hollow.

## Implications

- When the impulse arises to _build a validator / classifier / scorer / checker for X_, X is almost always semantic. The impulse is the warning sign. Load `software-development/policy/no-semantic-validators` before writing the check.
- Policy on agent output lives in the agent's briefing, not in transport, validation, or scoring code that wraps the agent.

## Tensions

- **Defense-in-depth vs. trust.** Layered checks feel safer; each layer compounds drift when the heuristic shifts. Fewer layers, better briefings.
- **Automation cost vs. agent cost.** Code feels cheaper than agent inference. Over the lifetime of the codebase, code that grades content is more expensive — drift, gaming, removal — than the inference it replaced.
