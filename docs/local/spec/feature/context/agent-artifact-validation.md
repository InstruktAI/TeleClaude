---
description: 'Schema, section, and Required-reads-order validation for command source artifacts, plus the identity contract every skill entrypoint keeps.'
visibility: 'public'
---

# Agent Artifact Validation — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Agent artifact validation is the context gate that runs during source validation.
It enforces the skill identity contract: every `SKILL.md` must declare `name`
and `description`, with `name` equal to its folder. Skill bodies are never
graded against TeleClaude's taxonomy.

Skills are the one artifact kind. Subagent definitions are not an artifact
kind: none is validated, and a file under an agents/ kind directory other than
skills/ is refused as outside the artifact model. What an agent is assigned at
session start is a procedure, validated under the snippet contracts
(`local/projects/teleclaude/spec/feature/context/snippet-frontmatter-validation`),
never here. Third-party skill bodies and supporting package Markdown retain
their human-authored structure.

A non-ignored, unrecognized entry directly under `agents/`, including a stray
untracked file, is refused with a path-specific finding; Git-ignored entries
there are skipped.

Validation is scoped to the source paths under review: a supporting file inside
a skill package resolves to that package's entrypoint, and commit-bound
validation checks staged source and refuses any finding.

## Canonical fields

### Use cases

#### UC-AAV1: A maintainer can publish an upstream skill without rewriting its body

```gherkin
Scenario: Keep the upstream skill package structure
  Given a maintainer selects an upstream skill package with valid identity
  When they prepare that package for publication
  Then its authored body structure is accepted unchanged
```

#### UC-AAV2: A repository's artifact sources are validated within its declared reach

#### UC-AAV3: Scoped validation grades the artifacts in its path set

#### UC-AAV4: The commit gate validates the artifacts in its pathspec

#### UC-AAV5: An empty command companion is accepted as a retirement

#### UC-AAV6: A file git ignores under agents/ is not an artifact source

#### UC-AAV7: A home owner can offer a local skill to agents in that home

```gherkin
Scenario: Publish a skill for a company or person home
  Given a company or person home has a local skill package with valid identity
  When the owner publishes that package for the home
  Then the skill is accepted in the home's own artifact layout and reaches its agents
```

### Cross-context references

- agent_runtime — the deployed artifacts ultimately drive what the agent CLI
  loads at runtime; validation here is the upstream gate that protects the
  inflation pipeline from malformed sources.

## Known caveats

- Required-reads ref-existence is checked only at the outer artifact-level
  validation when the refs list is non-empty; the underlying body-structure
  check does not verify existence in isolation.
- The heading collector skips fenced code blocks so example markdown inside
  code fences does not produce false H2 hits.
- Skill discovery requires the `SKILL.md` filename specifically. Its identity
  metadata is always validated, and its body is never graded against TeleClaude's
  taxonomy. Supporting Markdown remains opaque package content in either skill scope.
- The reach gate refuses rather than skips: a global source outside a repository's
  declared reach is a validation finding naming the file. Registered projects
  publish no global skills; only the mother's `agents/global/skills/<name>/`
  folders reach the catalog.
- `parameters` entries that are not dicts, or dicts missing the `name` string,
  are rejected before the duplicate-name check runs.
