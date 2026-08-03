---
description: 'Schema, section, and Required-reads-order validation for agents, commands, and skills source artifacts.'
visibility: 'public'
---

# Agent Artifact Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Agent artifact validation is the context gate that runs over normalized authored
artifacts during `telec sync`. It enforces the shape those artifacts must hold so
the downstream CLI help text, skill manifests, and inflation pipeline produce
predictable output across Claude, Codex, and Gemini deployments. Human-curated
third-party packages published from registered projects' `agents/skills/<name>/`
folders are pass-through sources: Sync renders and publishes them but does not
grade their Markdown against TeleClaude's authored-artifact taxonomy.

Artifacts share a common shell — frontmatter, H1 title, optional Required
reads, section order — but split on the presence of a role activation line:
commands and agents declare a role; skills do not.

## Canonical fields

### Use cases

```
Scenario: Command artifact missing H1
  Given a command Markdown file with frontmatter but no leading H1 line
  When the artifact validator runs
  Then a "missing H1" error is reported
```

```
Scenario: Skill carries a role activation line
  Given a SKILL.md whose body contains "You are now the Researcher"
  When validation runs
  Then the role activation line is rejected for skills
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
Scenario: Skill folder name does not match frontmatter name
  Given a skill directory whose SKILL.md frontmatter declares name "bar"
  And the directory itself is named "foo"
  When the artifact validator walks the skills tree
  Then the folder-name mismatch is reported
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
Scenario: Published third-party skill Markdown keeps its upstream structure
  Given a registered project publishes a folder at agents/skills/<name>/
  And the folder contains SKILL.md and optional supporting Markdown resources
  When telec sync processes the global skill publication surface
  Then none of those Markdown files is checked for TeleClaude headings, section order, role lines, or taxonomy shape
  And the package is rendered through the artifact output pipeline without rewriting its authored structure
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
- Skill discovery requires the `SKILL.md` filename specifically; other
  Markdown files inside a skill subdirectory are not treated as skills and are
  silently ignored.
- The normalized-artifact walker still treats supporting Markdown inside an
  authored skill as resources rather than separate artifacts. The global skill
  publication path goes further: it treats the complete package as human-curated
  upstream content and applies no authored-artifact body schema to any file in it.
- The mother-project gate remains a silent skip for global commands, agents,
  addenda, and masters. Registered projects' `agents/skills/<name>/` folders are
  collected separately and do not make the rest of their `agents/` tree global.
- `parameters` entries that are not dicts, or dicts missing the `name` string,
  are rejected before the duplicate-name check runs.
