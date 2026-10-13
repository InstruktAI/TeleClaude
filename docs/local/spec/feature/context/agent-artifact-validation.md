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

## Canonical fields

### Use cases

```
Scenario: Every skill entrypoint has identity metadata
  Given SKILL.md exists in a skill source folder of any tier
  And its name or description frontmatter is missing, empty, or its name differs from <name>
  When artifact validation runs
  Then the entrypoint is rejected
```

#### UC-AAV1: A skill body stays outside taxonomy validation

```gherkin
Scenario: An agent validates a skill package that retains its upstream body structure
  Given an agent authors a SKILL.md with valid identity metadata
  And its headings and section order do not match TeleClaude's normalized schema
  When the agent runs artifact validation
  Then the skill body produces no taxonomy-validation finding
```

#### UC-AAV2: A repository's artifact sources are validated within its declared reach

```gherkin
Scenario: An agent validates a repository whose sources exceed its declared reach
  Given a repository that is not the mother declares the domains it publishes
  And it carries authored sources under agents/local/ and agents/global/
  When the agent runs artifact validation
  Then every agents/local/ source is validated as authored input
  And a global skill is refused with a finding naming the file and the reach it exceeds
  And nothing under .agents/ is read as an authored source
```

```
Scenario: Published or project-local supporting Markdown keeps its upstream structure
  Given a skill package exists in a skill source folder of any tier
  And the folder contains SKILL.md and optional supporting Markdown resources
  When recorded-commit publication processes the skill
  Then supporting Markdown is not checked for TeleClaude headings, section order, role lines, or taxonomy shape
  And SKILL.md receives identity validation
  And the package is rendered through the artifact output pipeline without rewriting its authored structure
```

#### UC-AAV3: Scoped validation grades the artifacts in its path set

```
Scenario: Scoped validation grades the artifacts in its path set
  Given a path set naming a skill entrypoint under a configured artifact source
  When artifact validation runs scoped to that path set
  Then the named artifact is validated against the skill identity contract
  And a supporting file inside a skill package resolves to that package's SKILL.md
```

#### UC-AAV4: The commit gate validates the artifacts in its pathspec

```
Scenario: The commit gate validates the artifacts in its pathspec
  Given a commit whose staged file set names a skill source
  When the commit's pre-commit gate runs, whichever route started the commit
  Then artifact validation runs scoped to the staged file set, reading the staged content
  And a validation finding refuses the commit
```

#### UC-AAV5: An empty command companion is accepted as a retirement

#### UC-AAV6: A file git ignores under agents/ is not an artifact source

```
Scenario: An agent runs full lint with an ignored file and a stray file under agents/
  Given git ignores a file directly under agents/, such as operating-system folder metadata
  And a file git does not ignore sits untracked directly under agents/
  When the agent runs lint across the whole repository
  Then the ignored file produces no artifact finding
  And the untracked file is refused with a finding naming it
  And that finding appears in the lint output the agent reads
```

#### UC-AAV7: A company or person home's own artifact sources are validated in their flat layout

```gherkin
Scenario: An agent commits agent artifacts in a company or person home
  Given a company or person home carrying sources directly under its own agents/skills/
  When artifact validation runs over paths that home owns
  Then each SKILL.md is validated against the skill identity contract
  And a file under that home's agents/ outside skills/ is refused with a finding naming it
  And no global or local tier directory is required in that home
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
