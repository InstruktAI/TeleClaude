---
activation_trigger: Use when invoked as the project-category memory miner via /extract-memory-project
  against a session mirror
delivered_by:
- v2-memory
description: Thin wrapper around the general memory-extraction procedure for the project-category
  memory miner. Binds the agent to the project vocabulary, cross-project routing rules,
  and out-of-scope boundary defined in the project extraction feature spec.
visibility: public
---

# Memory Extraction — Project — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/memory-extraction/overview.md
- @docs/project/spec/feature/memory/extraction-project.md

## Goal

Extract durable observations about projects from a session mirror, classified into the project-category predicate vocabulary, saved as triples via the scraper-only write path. Cross-project routing: an observation may pertain to a different project than the session itself runs in, and is routed accordingly.

## Preconditions

All preconditions from the general procedure apply. Plus:

- The agent's category for this run is `project`.
- The agent has loaded the project-category vocabulary, subject-resolution rules, and cross-project routing rules from the feature spec (above).
- The agent has required reads for every known project on the machine, so it can identify which project a candidate observation pertains to (not only the session's own project).

## Steps

Execute the general procedure with these category-specific bindings:

- **Category:** `project`
- **Vocabulary:** as enumerated in the project extraction feature spec — `convention`, `decided`, `friction`, `requirement`, `gotcha`, `architectural-fact`, `constraint`, `deferral`, `dependency`, `pattern`, `anti-pattern`, `mentioned`, `open-question`.
- **Subject:** the project slug the observation pertains to. May be the session's own project, or a different project surfaced in conversation. Observations that cannot be clearly attributed to a specific project are discarded (NEVER default to the session's project as a fallback for ambiguous content).
- **Scope:** observations relevant to a project. Human-individual observations belong to the human-category agent. Behavioral patterns are out of scope.

## Outputs

As per the general procedure, scoped to project-category rows.

## Discipline

Follow the memory-extraction procedure's discipline, with two project-category emphases:

1. **No default-to-session-project.** Observations not clearly tied to a specific project are discarded. Silently attributing ambiguous content to the session's own project pollutes that project's memory with noise.
2. **Cross-project routing requires explicit identification.** When an observation pertains to a project OTHER than the session's own, the agent must explicitly identify which project, using the required-reads registry of known projects. If the target project isn't known, the observation is discarded.

## Recovery

Per the general procedure.
