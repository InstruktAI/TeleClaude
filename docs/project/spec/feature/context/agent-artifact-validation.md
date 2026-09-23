---
description: 'Schema, section, and Required-reads-order validation for command source artifacts, plus the identity contract every skill entrypoint keeps.'
visibility: 'public'
---

# Agent Artifact Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Agent artifact validation is the context gate that runs during source validation.
It enforces the normalized shape of commands, plus a skill identity
contract. Every `SKILL.md` must declare `name` and `description`, with `name`
equal to its folder. Skill bodies are never graded against TeleClaude's taxonomy.


Validated commands share a common shell — frontmatter, H1 title, optional
Required reads, section order, and a role activation line. Subagent definitions
are not an artifact kind: none is validated, and a file under an agents/ kind
directory other than commands/ or skills/ is refused as outside the artifact
model. Third-party skill bodies and supporting package Markdown retain their
human-authored structure.


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
  Given a command artifact whose first H2 is "## Purpose"
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
  Then the ordering error is reported (commands → skills)
```

#### UC-AAV2: A repository's artifact sources are validated within its declared reach

```gherkin
Scenario: An agent validates a repository whose sources exceed its declared reach
  Given a repository that is not the mother declares the domains it publishes
  And it carries authored sources under agents/project/ and agents/global/
  When the agent runs artifact validation
  Then every agents/project/ source is validated as authored input
  And a global command under a domain the repository publishes is validated as authored input
  And a general command, a global skill, or a command under a domain the repository does not publish is refused with a finding naming the file and the reach it exceeds
  And nothing under .agents/ is read as an authored source
```

<!-- planned-change:retire-docs-watcher -->
```
Scenario: Published or project-local supporting Markdown keeps its upstream structure
  Given a skill package exists in a skill source folder of any tier
  And the folder contains SKILL.md and optional supporting Markdown resources
  When telec sync processes the skill
  Then supporting Markdown is not checked for TeleClaude headings, section order, role lines, or taxonomy shape
  And SKILL.md receives identity validation
  And the package is rendered through the artifact output pipeline without rewriting its authored structure
```
<!-- change:retire-docs-watcher -->
```
Scenario: Published or project-local supporting Markdown keeps its upstream structure
  Given a skill package exists in a skill source folder of any tier
  And the folder contains SKILL.md and optional supporting Markdown resources
  When recorded-commit publication processes the skill
  Then supporting Markdown is not checked for TeleClaude headings, section order, role lines, or taxonomy shape
  And SKILL.md receives identity validation
  And the package is rendered through the artifact output pipeline without rewriting its authored structure
```
<!-- /planned-change:retire-docs-watcher -->


#### UC-AAV3: Scoped validation grades the artifacts in its path set

```
Scenario: Scoped validation grades the artifacts in its path set
  Given a path set naming a command and a skill entrypoint under a configured artifact source
  When artifact validation runs scoped to that path set
  Then each named artifact is validated against the contract for its kind
  And a supporting file inside a skill package resolves to that package's SKILL.md
```

#### UC-AAV4: The commit gate validates the artifacts in its pathspec

```
Scenario: The commit gate validates the artifacts in its pathspec
  Given a commit pathspec naming a command or skill source
  When telec code commit runs
  Then artifact validation runs scoped to that pathspec
  And a validation finding refuses the commit
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
