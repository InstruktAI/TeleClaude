---
description: 'Breath-aware taxonomy for agent skills defining exploratory, disciplinary, and creative lanes to guide procedure extraction and wrapper alignment.'
id: 'general/concept/skill-taxonomy'
scope: 'global'
type: 'concept'
---

# Skill Taxonomy — Concept

## What

Agent skills are not interchangeable. Each activates a different cognitive mode: some diverge before converging, some apply structured rigor, some generate artifacts directly. The taxonomy names these modes and uses them to guide how skills are structured — specifically, which skills should carry long-form procedure content inline and which should reference extracted procedure docs.

Three lanes:

| Lane             | What it does                                                                                                    | Example skills                              |
| ---------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| **Exploratory**  | Opens space. Diverges before converging. Guides diagnosis, discovery, or design before any fix or build begins. | brainstorming, systematic-debugging         |
| **Disciplinary** | Applies structured rigor to a defined scope. Validates, reviews, or audits against known criteria.              | next-code-reviewer, test-driven-development |
| **Creative**     | Generates or transforms artifacts. Produces UI, content, or designs directly.                                   | frontend-design                             |

## Why

Exploratory skills pair naturally with extracted procedure docs because their value is in the multi-step workflow, not the wrapper, and the procedure logic is reusable independently of any skill invocation. Wrapper bloat increases drift risk for content that rarely changes.

Disciplinary and creative skills carry context that is often too entangled with wrapper structure to separate cleanly — they are deferred to later passes.

---

## Exploratory lane — migration pass 1

### In-scope skills (5)

| Skill                        | Why exploratory                                                                |
| ---------------------------- | ------------------------------------------------------------------------------ |
| `brainstorming`              | Divergent design exploration — opens options before closing on a solution      |
| `systematic-debugging`       | Root cause diagnosis — traces evidence before proposing any fix                |
| `next-silent-failure-hunter` | Error path diagnosis — audits failure handling before recommending changes     |
| `tech-stack-docs`            | Documentation research — gathers authoritative sources before writing snippets |
| `youtube`                    | Information gathering and research — retrieves and processes external content  |

### Excluded from this pass (4 non-exploratory unmigrated skills)

| Skill                            | Lane         | Reason excluded                                                 |
| -------------------------------- | ------------ | --------------------------------------------------------------- |
| `receiving-code-review`          | Disciplinary | Review-feedback processing — structured rigor, not discovery    |
| `test-driven-development`        | Disciplinary | Rigid RED-GREEN-REFACTOR workflow — discipline, not exploration |
| `verification-before-completion` | Disciplinary | Completion gate — evidence validation, not discovery            |
| `frontend-design`                | Creative     | Artifact generation — produces UI directly, not diagnostic      |

### Already-migrated skills (future-pass candidates)

These 7 skills already use `## Required reads` to reference policy/spec docs but retain inline procedure content. Full procedure extraction is deferred to a follow-up pass.

`next-code-reviewer`, `next-code-simplifier`, `next-comment-analyzer`, `next-test-analyzer`, `next-type-design-analyzer`, `research`, `git-repo-scraper`

## See Also

- ~/.teleclaude/docs/general/principle/breath.md — The diverge/hold/converge cycle that exploratory skills embody
- ~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md — Schema for the procedure docs that wrapper skills reference
