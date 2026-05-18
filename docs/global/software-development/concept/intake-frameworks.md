---
description: 'Named menu of established business-analysis and requirements-engineering frameworks used during intake. Each carries an objective and a trigger condition that activates the agent''s trained associations.'
domain: 'software-development'
id: 'software-development/concept/intake-frameworks'
scope: 'domain'
type: 'concept'
visibility: 'public'
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
| **Specification by Example / Gherkin** | Gojko Adzic, Dan North | Express behavioral contracts as "Given X, when Y, then Z" examples that translate cleanly to executable tests. | Test-specs phase only. Not used during intake — PRD success criteria stay outcome-shaped in PO language. |

### How procedures reference this concept

A procedure that needs intake work lists the relevant frameworks by name with a one-line use-when description. The intake procedure maps frameworks to **PRD template sections** (BMAD-aligned), so the agent applies each tool where it fits rather than running all of them uniformly:

| PRD template section | Apply when filling |
| --- | --- |
| Goal | **JTBD** — restate the request as "the user wants the system to do X for Y under Z." |
| Why | **5 Whys** — when the surface ask looks like a proxy for an underlying need. |
| Scope | **MoSCoW** — categorize every surfaced item as Must / Should / Could / Won't with rationale. |
| Success criteria | Outcome-shaped prose in PO language — observable indicators of success ("the user can do X within Y", "the system handles N concurrent X"). **Not Gherkin.** Gherkin belongs to the test-specs phase, not the PRD. |
| Risks and unknowns | **Pre-mortem** — imagine failure modes, surface risks. |
| (throughout) | **Socratic questioning** — clarity probes. |

**Default-on (intake):** 5 Whys, JTBD, MoSCoW, Pre-mortem. The agent applies these per the section mapping above. Gherkin is default-on for the **test-specs phase**, not for intake.

**Available-but-not-default:**

- **Impact Mapping** — heavyweight (actor → impact → deliverables tree). Apply only when the work item's scale justifies the structure (large or architectural work where actor-to-deliverable mapping is genuinely non-trivial).
- **Volere shell** — requirement-level format. The PRD template sections already cover most of what Volere does at the document level. Reach for Volere only on compliance-heavy work where formal requirement structure is required.

The procedure does not describe each framework's internal steps. The named framework carries that load through the agent's trained associations.

### Relation to BMAD

The BMAD method (Breakthrough Method for Agile AI-Driven Development) uses a similar pattern: PRD → Architecture → Stories, with elicitation per phase. This concept aligns with BMAD on terminology (PRD), artifact handoffs, and structured templates. The framework menu above provides the elicitation tools BMAD uses without prescribing BMAD's specific persona layering — the platform's own role pattern (general agent + per-step procedural awareness loading) sits over the top.

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

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
