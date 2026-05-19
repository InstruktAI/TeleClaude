---
id: 'project/spec/feature/context/agent-artifact-validation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Schema, section, and Required-reads-order validation for agents, commands, and skills source artifacts.'
---

# Agent Artifact Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Agent artifact validation is the v1 gate that runs over the `agents/`,
`commands/`, and `skills/` source trees during `telec sync`. It enforces the
shape that every agent-facing artifact must hold so the downstream CLI help
text, skill manifests, and inflation pipeline produce predictable output
across Claude, Codex, and Gemini deployments.

Artifacts share a common shell — frontmatter, H1 title, optional Required
reads, section order — but split on the presence of a role activation line:
commands and agents declare a role; skills do not.

## Canonical fields

### Use cases

```
Scenario: Command artifact missing H1
  Given a command Markdown file with frontmatter but no leading H1 line
  When validate_artifact runs
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
  Given a directory skills/foo/SKILL.md with frontmatter name "bar"
  When validate_all_artifacts walks the skills tree
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
  When _validate_required_reads_order runs
  Then the ordering error is reported (commands → agents → skills)
```

```
Scenario: Non-mother project's local agents/ is not walked
  Given a project where is_mother_project evaluates False
  And the project contains files under its own agents/ directory
  When validate_all_artifacts runs
  Then the validator's global_sources list is empty
  And the project's own agents/ tree is NOT walked or validated
  And no error is reported about those files
  And only the project's .agents/ tree is processed
```

### Implementation pointers (v1)

- `teleclaude/resource_validation/__init__.py:109-130` —
  `_extract_artifact_required_reads()`
- `teleclaude/resource_validation/__init__.py:141-152` —
  `validate_artifact_frontmatter()`
- `teleclaude/resource_validation/__init__.py:155-171` — `parameters` shape
- `teleclaude/resource_validation/__init__.py:236-251` — role activation line
- `teleclaude/resource_validation/__init__.py:254-303` — section order
- `teleclaude/resource_validation/__init__.py:306-330` — body structure +
  Required reads placement
- `teleclaude/resource_validation/__init__.py:333-342` —
  `_validate_required_reads_order()`
- `teleclaude/resource_validation/__init__.py:354-365` — `validate_artifact()`
- `teleclaude/resource_validation/__init__.py:373-425` —
  `validate_all_artifacts()` walks the trees
- `teleclaude/sync.py:50` — sync invocation

### Cross-context references

- agent_runtime — the deployed artifacts ultimately drive what the agent CLI
  loads at runtime; validation here is the upstream gate that protects the
  inflation pipeline from malformed sources.

## Known caveats

- Required-reads ref-existence is checked only by the wrapper
  `validate_artifact()` when the refs list is non-empty; the underlying
  `validate_artifact_body()` does not verify existence in isolation.
- `_collect_artifact_headings()` skips fenced code blocks so example markdown
  inside code fences does not produce false H2 hits.
- Skill discovery requires the `SKILL.md` filename specifically; other
  Markdown files inside a skill subdirectory are not treated as skills and are
  silently ignored.
- The mother-project gate is applied here as a silent skip: when
  `is_mother_project` is False, the validator's `global_sources` list is
  empty and the project's own `agents/` tree is never walked. There is no
  error path that fails non-mother projects for having `agents/` content;
  the contents are simply ignored. See `mother-project-publishing-gate`.
- `parameters` entries that are not dicts, or dicts missing the `name` string,
  are rejected before the duplicate-name check runs.
