---
id: 'software-development/concept/intake-frameworks'
type: 'concept'
domain: 'software-development'
scope: 'domain'
description: 'Named menu of established business-analysis and requirements-engineering frameworks used during intake. Each carries an objective and a trigger condition that activates the agent''s trained associations.'
---

# Intake Frameworks — Concept

## What

A menu of established, widely-documented business-analysis and requirements-engineering frameworks that intake procedures (discovery, requirements drafting, planning) can invoke by name. Naming a framework activates the agent's trained associations for that framework — denser instruction than describing the procedure freshly, and more robust because the agent draws on its training rather than parsing fresh prose.

### The menu

| Framework | Origin | Objective | Trigger |
| --- | --- | --- | --- |
| **5 Whys** | Toyota Production System (Taiichi Ohno) | Drill from a surface request to the underlying root need. | Intent reading. The stated request looks like a proxy for an underlying need. |
| **Jobs To Be Done (JTBD)** | Clayton Christensen | Restate a feature request as "the user wants the system to do X under conditions Y." Cuts feature-language to underlying purpose. | Intent reframing. Producing the user-facing reframe. |
| **Impact Mapping** | Gojko Adzic | Start from goal → identify actors → enumerate impacts on each → derive deliverables. Tree-shaped, naturally branches into independent avenues. | Expansion. Surfacing the structure of what serving an intent requires. |
| **Pre-mortem analysis** | Gary Klein | Imagine the work shipped and failed; reason backwards to surface risks before they're abstract. | Risk surfacing. One of the named expansion avenues during discovery. |
| **MoSCoW prioritization** | Dai Clegg / DSDM | Force every surfaced item into Must / Should / Could / Won't with explicit rationale. | Tailor-fit. Trimming a wide expansion to what fits the actual intent. |
| **Volere shell** | Suzanne and James Robertson | Structure each requirement with Description, Rationale, Source, Fit Criterion, Customer Satisfaction/Dissatisfaction. | Requirements format reference. Aligns with `preparation-artifact-quality`. |
| **Specification by Example / Gherkin** | Gojko Adzic, Dan North | Express success criteria as "Given X, when Y, then Z" examples that bridge to executable tests. | Bridging confirmed reframe to test specs. |

### How procedures reference this concept

A procedure that needs intake work lists the relevant frameworks by name with a one-line use-when description. Example, from a discovery procedure:

> Apply the framework that fits the moment. Each is named established practice — use the named approach, do not invent alternates.
>
> - **5 Whys** — when the user's input looks like a proxy for an underlying need.
> - **Impact Mapping** — when expanding from intent into actors, impacts, deliverables.
> - **Pre-mortem** — when surfacing risks during expansion.
> - **MoSCoW** — when trimming surfaced material against need-fitness.
> - **JTBD** — when authoring the reframe back to the user.
> - **Gherkin** — when expressing success criteria in test-bridgeable form.
> - **Volere** — when shaping the eventual requirements artifact.

The procedure does not describe each framework's internal steps. The named framework carries that load.

### Additions to the menu

To be added to this concept, a candidate framework must:

1. Be widely documented in training data (Claude, Codex, and Gemini all carry rich associations). Test: a baseline LLM correctly summarizes the framework when given only its name.
2. Have a single canonical name in the literature. Aliases dilute priming.
3. Serve an intake objective not already covered by the existing menu. Overlapping frameworks are redundant priming.

If a framework cannot meet these bars, it is not added. The procedure either describes the cognitive move it needs in prose, or accepts that the move is too specialized to be primed reliably by name alone.

## Why

- **Density.** "Apply Impact Mapping" activates a full structured method. Describing the same method in prose costs paragraphs and reproduces less faithfully.
- **Cross-model legibility.** Well-documented frameworks have rich training associations across Claude, Codex, and Gemini. Niche or proprietary names do not. The framework menu restricts to widely-documented practice so priming is robust across model families.
- **Legibility to humans.** BA/PM-trained humans recognize these names. The agent's output remains inspectable.
- **Maintainability.** Swapping a framework reference is a one-line change in a procedure; rewriting a custom procedure is not.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discovery-v2.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
