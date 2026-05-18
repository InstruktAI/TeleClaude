---
description: 'Code that classifies, scores, judges, evaluates, or auto-edits content semantics is doing what intelligence does. Trust the briefing; trust the agent.'
id: 'software-development/principle/intelligence-boundaries'
scope: 'domain'
type: 'principle'
visibility: 'public'
---

# Intelligence Boundaries — Principle

## Principle

When the question is "is this content meaningful, important, well-formed,
complete, on-topic, or correct?", the answer comes from intelligence — the
agent reading it — not from code that grades it. Code that classifies,
scores, judges, evaluates, or auto-edits free-text content substitutes
automation for judgment, and the substitution decays.

## Rationale

Heuristics built on regex, word counts, or hardcoded vocabulary tables are
correct only against today's language, today's model, today's prompt. They
go wrong silently when any of those shift. Auto-editors are worse: they
rewrite the agent's intent to satisfy their own grading. Once a rubric
exists in code, agents learn to write to the rubric — the rubric becomes the
artifact and the artifact becomes hollow.

The work the rubric pretends to do is judgment work. Judgment work belongs
to intelligence. Policy on what an agent should produce belongs in the
agent's briefing — read once, applied with context — not in transport,
validation, or scoring code that wraps the agent and second-guesses it.

## Implications

- Policy on agent output lives in the agent's briefing, not in transport,
  validation, or scoring code.
- Detection patterns to refuse:
  - Hardcoded vocabulary tables for content categorization (`_ACK_*`,
    `_KEYWORDS`, `_HINTS`, `_PHRASES`).
  - Regex on free text for semantic decisions.
  - Word-count thresholds for "is this important?" / "is this meaningful?".
  - Predicates like `is_meaningful` / `is_ack` / `should_emit` /
    `is_actionable` on natural language.
  - Auto-fixers that rewrite agent artifacts to match structural rubrics
    (e.g., regex section-header grading then regex-driven section
    insertion).
  - Sentiment, completeness, or quality scoring of agent output.
- Mechanical lookups are not violations: "does this commit SHA exist?",
  "does this snippet ID resolve?", "does this enum value match?", "is this
  path under the project root?" — these are deterministic, not intelligence.
- Structural code is not violation: parsing a known wire format with a
  documented schema, computing ordinal comparisons on enum values, mapping
  IDs to records, normalizing whitespace.
- Rule of thumb: when the impulse is "let me build a validator / classifier
  / scorer / checker for X," X is almost always semantic and the right
  answer is to write the rule into the briefing the agent reads, not into
  code the agent wraps. The impulse to build the check is the warning sign.

## Tensions

- **Defense-in-depth vs. trust.** Layered checks feel safer. But each layer
  of code-grading-the-agent compounds the failure when the heuristic drifts.
  Fewer layers, better briefings.
- **Determinism vs. judgment.** Some semantic decisions look mechanical
  ("is this comment stale?", "is this finding actionable?"). They aren't. If
  the inputs include free-text written by an agent, the decision needs
  intelligence.
- **Automation cost vs. agent cost.** Code feels cheaper than agent
  inference. Over the lifetime of the codebase, code that grades content is
  more expensive — drift, gaming, maintenance, removal — than the inference
  it tried to replace.
- **Process rigor vs. process theater.** Rubrics that grade agent output
  produce measurable artifacts (scores, counts, pass/fail). The
  measurability feels like rigor. It is theater. The artifact looks rigorous;
  the agent learns to satisfy the artifact; the underlying quality drifts.
