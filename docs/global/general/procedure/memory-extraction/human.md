---
id: general/procedure/memory-extraction/human
type: procedure
domain: general
scope: global
visibility: public
delivered_by: [v2-memory]
activation_trigger: 'Use when invoked as the human-category memory miner via /extract-memory-human against a session mirror'
description: Thin wrapper around the general memory-extraction procedure for the human-category memory miner. Binds the agent to the human vocabulary, subject-resolution rules, and out-of-scope boundary defined in the human extraction feature spec.
---

# Memory Extraction — Human — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/memory-extraction/overview.md
- @docs/project/spec/feature/memory/extraction-human.md

## Goal

Extract durable facts about the human from a session mirror, classified into the human-category predicate vocabulary, saved as triples via the scraper-only write path.

## Preconditions

All preconditions from the general procedure apply. Plus:

- The agent's category for this run is `human`.
- The agent has loaded the human-category vocabulary and subject-resolution rules from the feature spec (above).

## Steps

Execute the general procedure with these category-specific bindings:

- **Category:** `human`
- **Vocabulary:** as enumerated in the human extraction feature spec — `role`, `expertise`, `working-on`, `prefers`, `dislikes`, `goal`, `constraint`, `decided`, `mentioned`, `relationship`.
- **Subject:** the human's email when resolvable from the session record; the identity-context string (e.g., `whatsapp:31612345678`) otherwise. NEVER mix forms for the same human across sessions — that creates two subjects for one person and breaks continuity.
- **Scope:** facts about the human as a person. Project-relational observations belong to the project-category agent, not here. Behavioral patterns are out of scope entirely.

## Outputs

As per the general procedure, scoped to human-category rows.

## Discipline

Follow the memory-extraction procedure's discipline, with one human-category emphasis: avoid emotional interpretation. The temptation to read mood, frustration, satisfaction into the human's words is strong; resist it. Save only what the human demonstrably stated or chose. "The human said X" is fact. "The human felt X" is interpretation, unless the human stated that feeling explicitly.

## Recovery

Per the general procedure.
