---
id: project/spec/feature/memory/extraction-project
type: spec
domain: software-development
scope: project
visibility: public
delivered_by: [v2-memory]
description: Project memory extraction — the memory-miner agent that reads a session mirror, classifies observations about a project as triples in the project-category vocabulary, and saves them through the scraper-only write path.
---

# Project Memory Extraction — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

Project memory extraction is the capability that turns a session's conversation into durable observations about projects discussed in it. A dedicated extraction agent (the project-category memory miner) reads the session's mirror text, identifies facts about a project (conventions, decisions, frictions, requirements, gotchas, open questions, etc.), dedups against the codified library, and persists each surviving observation as a triple in the project-category vocabulary.

This feature is one of two extraction features under the memory pillar (the other is `extraction-human`). Both share the dedup discipline, the append-only write semantics, and the mirror-id provenance defined by the memory domain spec. They differ in subject, vocabulary, and scope — captured here for the project-category agent.

Project memory is the upstream feed for project artifacts. Downstream pattern-matcher jobs read accumulated project triples and produce todos, doc-snippet drafts, and other concrete project outputs. The extraction agent does NOT produce those artifacts directly.

## Canonical fields

### Subject resolution

Subject is the **project slug** (e.g., `teleclaude`, `help-desk`). The agent identifies which project an observation pertains to from the session context:

- The session's own project is the default candidate.
- An observation can pertain to a DIFFERENT project than the session's own (e.g., a help-desk session producing an observation about the TeleClaude project). The agent has required reads for all known projects on the machine and routes observations accordingly.
- Observations not clearly tied to a specific project are discarded (not saved under any default).

### Predicate vocabulary (closed)

| Predicate            | Captures                                             |
| -------------------- | ---------------------------------------------------- |
| `convention`         | A way-of-working that emerged or was affirmed        |
| `decided`            | A decision made (rationale baked into object)        |
| `friction`           | Something that broke, rubbed, or surprised painfully |
| `requirement`        | An explicit ask — upstream of a future todo          |
| `gotcha`             | Counter-intuitive behavior, quiet trap               |
| `architectural-fact` | Design state of the system                           |
| `constraint`         | A limit the project enforces                         |
| `deferral`           | An explicit postponement (reason in object)          |
| `dependency`         | What this project relies on                          |
| `pattern`            | A recurring approach that works                      |
| `anti-pattern`       | A recurring approach that doesn't                    |
| `mentioned`          | Topic salience for this project                      |
| `open-question`      | Unresolved items, capture-and-revisit                |

Free-form predicates outside this list are rejected at save.

### Scope

This agent extracts triples **about a project as an entity**. The boundary:

- **In scope:** observations relevant to a project that downstream pattern-matchers could turn into project artifacts (doc snippets, todos). Conventions surfaced, decisions made, frictions encountered, requirements stated, architectural facts revealed.
- **Out of scope (defer to human extraction):** anything about the human's individual traits, preferences, goals, constraints that are not project-relational. Those belong to the human-category agent.
- **Out of scope (discard entirely):** observations not tied to any specific project (the agent must NOT default to "the session's project" for content that isn't actually about that project); behavioral patterns (deferred skill-detection capability).

### Behavioral contract

#### Save a project observation

```
Given the project-category extraction agent has identified a candidate fact about a project in the session mirror
And the candidate is not substantively covered by any existing doc snippet
When the agent runs:
    telec memories save --category project --subject <project-slug> --predicate <p> --object <o> --source-mirror <mirror_id>
Then memory validates the predicate against the project-category vocabulary
And appends a new row to the memory store
And emits memory.observation.saved
```

#### Cross-project routing

```
Given a session running in project A produces an observation about project B
And the agent has required reads naming project B as a known project
When the agent saves
Then the agent uses project B's slug as the subject (not project A's)
And the observation lands in project B's memory corpus
```

#### Reject free-form predicate

```
Given the agent attempts to save with a predicate outside the project-category vocabulary
When the save is processed
Then memory rejects the save with a validation error naming the allowed predicates
And no row is written
```

#### Append-only — repeated observations are meaningful

```
Given the agent has previously saved (subject=teleclaude, predicate=friction, object="dedup discipline is mandatory before save")
And the agent extracts the same observation again from a later session
When the agent saves
Then memory appends a new row (does NOT dedup at write time)
And the two rows together signal salience to downstream pattern-matchers
```

#### Reject unattributable observation

```
Given the agent identifies a candidate observation that is not clearly tied to a specific project
When the agent considers saving it
Then the agent does NOT save it
And the observation is discarded (no default-to-session-project fallback)
```

## Allowed values

- `category`: `project` (this feature is scoped to the project category only).
- `predicate`: `convention`, `decided`, `friction`, `requirement`, `gotcha`, `architectural-fact`, `constraint`, `deferral`, `dependency`, `pattern`, `anti-pattern`, `mentioned`, `open-question`.

## Known caveats

- **Cross-project routing requires required reads.** The agent must be primed with a registry of known projects on the machine (typically the local project slugs plus any platforms it can resolve). Without this, cross-project observations can't be routed and would be discarded.
- **No default-to-session-project.** Observations not clearly tied to a specific project are discarded. The agent must NOT silently attribute ambiguous observations to the session's own project — that pollutes project memory with noise.
- **No interpretation.** The agent records demonstrated facts. "The project seems stuck" is interpretation, not a fact, and must not be saved.
- **No todos, no doc snippets.** Pattern-matcher jobs read project memory and produce those downstream. The extraction agent ONLY produces triples.
- **No skill candidates.** Behavioral patterns are not project memory.
