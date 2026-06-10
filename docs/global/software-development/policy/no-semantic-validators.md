---
description: 'Refuse code that grades, classifies, scores, or auto-edits agent free-text output. Mechanical lookups and schema parsing are allowed.'
visibility: 'public'
---

# No Semantic Validators — Policy

## Required reads

@~/.teleclaude/docs/general/principle/intelligence-boundaries.md

## Rules

### Refusal patterns

Refuse code that performs any of these against agent free-text output:

- Hardcoded vocabulary tables for content categorization (`_ACK_*`, `_KEYWORDS`, `_HINTS`, `_PHRASES`).
- Regex on free text for semantic decisions.
- Word-count thresholds for "is this important?" / "is this meaningful?".
- Predicates like `is_meaningful`, `is_ack`, `should_emit`, `is_actionable` on natural language.
- Auto-fixers that rewrite agent artifacts to match structural rubrics (regex section-header grading followed by regex-driven section insertion).
- Sentiment, completeness, or quality scoring of agent output.

### Allowed patterns

Mechanical lookups and structural code on deterministic data are not violations:

- "Does this commit SHA exist?", "does this snippet ID resolve?", "does this enum value match?", "is this path under the project root?" — deterministic checks against known data.
- Parsing a known wire format with a documented schema.
- Computing ordinal comparisons on enum values.
- Mapping IDs to records.
- Normalizing whitespace.

The line: if the input includes free text written by an agent, the decision needs intelligence. If the input is structured data with a documented schema, code is fine.

## Rationale

Heuristics built on language patterns decay silently when the language shifts. Auto-fixers turn agents into rubric-pleasers. Once a rubric exists in code, agents learn to write to the rubric — the rubric becomes the artifact and the artifact becomes hollow. Policy on what an agent should produce belongs in the agent's briefing — read once, applied with context — not in transport, validation, or scoring code that wraps the agent and second-guesses it.

## Scope

Code that wraps, validates, scores, or auto-edits agent free-text output. Most commonly: transport-layer message handlers, artifact validators, completion checkers, post-processors.

## Enforcement

Caught at review. Required-read mounted in:

- `software-development/procedure/lifecycle/work/build.md` — prevent before writing.
- `software-development/procedure/lifecycle/work/review-build.md` — catch in review.
- `software-development/procedure/lifecycle/work/fix-review.md` — prevent re-introduction during fix.

The baseline `intelligence-boundaries` principle carries the trigger heuristic; this policy carries the catalog.

## Exceptions

None.
