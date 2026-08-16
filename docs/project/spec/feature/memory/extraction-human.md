---
delivered_by:
  - v2-memory
description: Human memory extraction — the memory-miner agent that reads a session
  mirror, classifies observations about the human as triples in the human-category
  vocabulary, and saves them through the scraper-only write path.
visibility: public
---

# Human Memory Extraction — Spec

## What it is

Human memory extraction is the capability that turns a session's conversation into durable observations about the human who participated in it. A dedicated extraction agent (the human-category memory miner) reads the session's mirror text, identifies facts about the human as a person, dedups against the codified library, and persists each surviving observation as a triple in the human-category vocabulary.

This feature is one of two extraction features under the memory pillar (the other is `extraction-project`). Both share the dedup discipline, the append-only write semantics, and the mirror-id provenance defined by the memory domain spec. They differ in subject, vocabulary, and scope — captured here for the human-category agent.

## Canonical fields

### Subject resolution

Subject is the human's durable identifier:

- **Primary form: email.** Resolvable for most internal humans (admins, members, contributors) via the person config. The scraper reads the session record to determine the human's email when available.
- **Fallback form: identity-context string** (e.g., `whatsapp:31612345678`, `telegram:1234567`). Used when no email is resolvable — anonymous help-desk customers entering via platform connectors.
- Both forms are opaque strings, matched by exact equality. A future session for the same human re-uses the same subject value, accumulating triples over time.

### Predicate vocabulary (closed)

| Predicate      | Captures                                                |
| -------------- | ------------------------------------------------------- |
| `role`         | The human's role (admin, member, customer, contributor) |
| `expertise`    | Domains and depth the human holds expertise in          |
| `working-on`   | What the human is currently engaged with                |
| `prefers`      | Positive preferences (style, format, approach)          |
| `dislikes`     | Negative preferences                                    |
| `goal`         | Articulated goals                                       |
| `constraint`   | Hard constraints the human has stated                   |
| `decided`      | Choices the human made (rationale baked into object)    |
| `mentioned`    | Topics the human surfaced                               |
| `relationship` | Other humans in the human's orbit                       |

Free-form predicates outside this list are rejected at save.

### Scope

This agent extracts triples **about the human as a person**. The boundary:

- **In scope:** durable facts about who the human is, what they prefer/dislike, what they're working on, what they've decided, what they've mentioned, what they relate to.
- **Out of scope (defer to project extraction):** anything that is about the human's relationship to a specific project. E.g., "the human's feedback on TeleClaude's memory subsystem" is project memory (subject = `teleclaude`), not human memory. The moment an observation involves a project, it belongs to the project-extraction agent.
- **Out of scope (discard entirely):** generic observations not tied to a specific human; behavioral patterns (those would belong to a future skill-detection capability, currently deferred).

### Use cases

#### Save a human observation

```
Given the human-category extraction agent has identified a candidate fact about the human in the session mirror
And the candidate is not substantively covered by any existing doc snippet
When the agent runs:
    telec memories save --category human --subject <email-or-identity-context> --predicate <p> --object <o> --source-mirror <mirror_id>
Then memory validates the predicate against the human-category vocabulary
And appends a new row to the memory store
And emits memory.observation.saved
```

#### Reject free-form predicate

```
Given the agent attempts to save with a predicate outside the human-category vocabulary
When the save is processed
Then memory rejects the save with a validation error naming the allowed predicates
And no row is written
```

#### Reject project-relational observation

```
Given the agent identifies an observation about the human in relation to a specific project
When the agent considers saving it as human-category
Then the agent does NOT save it under human-category
And defers it to the project-extraction agent's scope (or discards if the project-extraction agent will pick it up independently from the same mirror)
```

#### Append-only — repeated observations are meaningful

```
Given the agent has previously saved (subject=alice@…, predicate=prefers, object="direct stewardship")
And the agent extracts the same observation again from a later session
When the agent saves
Then memory appends a new row (does NOT dedup at write time)
And the two rows together provide a frequency signal for downstream consumers
```

## Allowed values

- `category`: `human` (this feature is scoped to the human category only).
- `predicate`: `role`, `expertise`, `working-on`, `prefers`, `dislikes`, `goal`, `constraint`, `decided`, `mentioned`, `relationship`.

## Known caveats

- **Subject normalization.** The agent must use the email form when resolvable; identity-context fallback only when no email is available. Mixing forms for the same human across sessions creates two subjects for one person and breaks continuity.
- **No interpretation.** The agent records demonstrated facts. "The human seems frustrated" is interpretation, not a fact, and must not be saved.
- **Project-relational boundary is bi-directional.** The project-extraction agent has the same boundary in reverse. Both agents must respect the boundary or the same observation lands in two places.
- **No skill candidates.** Behavioral patterns (sequences of actions, repeated tool calls) are NOT memory and must not be saved under any predicate. Skill detection is a separate, deferred capability with a different data shape.
