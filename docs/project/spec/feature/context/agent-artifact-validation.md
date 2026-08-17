---
description: 'Schema, section, and Required-reads-order validation for agents, commands, and skills source artifacts.'
visibility: 'public'
---

# Agent Artifact Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Agent artifact validation is the context gate that runs during `telec sync`.
It enforces the normalized shape of commands and agents, plus a two-tier skill
contract. Every `SKILL.md` must declare `name` and `description`, with `name`
equal to its folder. A skill body is graded against TeleClaude's taxonomy only
when its frontmatter declares `teleclaude_taxonomy: true`.

Validated commands and agents share a common shell — frontmatter, H1 title,
optional Required reads, section order, and a role activation line. Third-party
skill bodies and supporting package Markdown retain their human-authored structure.

## Canonical fields

### Use cases

```
Scenario: Command artifact missing H1
  Given a command Markdown file with frontmatter but no leading H1 line
  When the artifact validator runs
  Then a "missing H1" error is reported
```

```
Scenario: Every skill entrypoint has identity metadata
  Given SKILL.md exists below agents/skills/<name>/ or .agents/skills/<name>/
  And its name or description frontmatter is missing, empty, or its name differs from <name>
  When artifact validation runs
  Then the entrypoint is rejected regardless of its taxonomy opt-in
```

```
Scenario: A third-party skill body stays outside taxonomy validation
  Given a validly identified SKILL.md does not declare teleclaude_taxonomy: true
  And its headings and section order do not match TeleClaude's normalized skill schema
  When artifact validation runs
  Then the body produces no taxonomy-validation finding
```

```
Scenario: A TeleClaude skill opts into the complete taxonomy
  Given a validly identified SKILL.md declares teleclaude_taxonomy: true
  When its H1, Required reads placement, normalized sections, inline references, or See Also references are invalid
  Then artifact validation rejects the skill entrypoint
```

```
Scenario: Command lacks the role activation line
  Given a command Markdown file with no "You are now the ..." line before the first regular H2
  When validation runs
  Then the missing role activation line is reported
```

```
Scenario: Section order does not match the artifact kind
  Given a command whose H2 order is "Inputs, Purpose, Outputs, Steps, Discipline"
  When section-order validation runs
  Then the wrong-order error is reported
  And the expected order "Purpose, Inputs, Outputs, Steps, Discipline" is named in the finding
```

```
Scenario: Required reads is not the first H2 in an artifact
  Given an agent artifact whose first H2 is "## Purpose"
  And a "## Required reads" H2 appears later
  When body-structure validation runs
  Then the Required-reads placement error is reported
```

```
Scenario: H3 heading present in an artifact
  Given any artifact containing an "### Example" H3
  When validation runs
  Then the H3 heading is rejected
```

```
Scenario: parameters contains duplicate names
  Given an artifact frontmatter parameters list with two entries named "target"
  When parameter-shape validation runs
  Then the duplicate "target" parameter is rejected
```

```
Scenario: Required reads orders refs incorrectly
  Given a Required reads block listing a skill ref before a command ref
  When the Required-reads ordering check runs
  Then the ordering error is reported (commands → agents → skills)
```

```
Scenario: Non-mother project's local agents/ is not walked
  Given a project that is not the Mother project
  And the project contains files under its own agents/ directory
  When the artifact validator walks the configured sources
  Then the global agent-source list is empty
  And the project's commands, agents, masters, and addenda under agents/ are NOT walked or validated
  And named folders under agents/skills are reserved for the separate global skill publication path
  And only the project's .agents/ tree is processed
```

```
Scenario: Published or project-local supporting Markdown keeps its upstream structure
  Given a skill package exists at agents/skills/<name>/ or .agents/skills/<name>/
  And the folder contains SKILL.md and optional supporting Markdown resources
  When telec sync processes the global skill publication surface
  Then supporting Markdown is not checked for TeleClaude headings, section order, role lines, or taxonomy shape
  And SKILL.md receives identity validation plus taxonomy validation only when explicitly opted in
  And the package is rendered through the artifact output pipeline without rewriting its authored structure
```

<!-- planned:command-migration-to-singular-telec-skill -->

```
Scenario: Project-local command artifacts are rejected with migration guidance
  Given a project-local command artifact exists at .agents/commands/<name>.md
  When telec sync validates that project's agent artifacts
  Then validation fails and the sync exits non-zero
  And the failure names each offending file path
  And the failure states that commands are TeleClaude-global and are not authorable from a project
  And the check is structural on artifact kind and location, grading no file content
```

```
Scenario: The global command corpus is unaffected by the project-local prohibition
  Given TeleClaude command artifacts exist under agents/commands/ in the Mother project
  And no project-local command artifacts exist under .agents/commands/
  When telec sync validates agent artifacts
  Then the global command artifacts validate and compile to the shared command corpus
  And no prohibition error is reported
```

<!-- /planned:command-migration-to-singular-telec-skill -->

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
  metadata is always validated, while body taxonomy is opt-in. Supporting Markdown
  remains opaque package content in either skill scope.
- The mother-project gate remains a silent skip for global commands, agents,
  addenda, and masters. Registered projects' `agents/skills/<name>/` folders are
  collected separately and do not make the rest of their `agents/` tree global.
- `parameters` entries that are not dicts, or dicts missing the `name` string,
  are rejected before the duplicate-name check runs.
