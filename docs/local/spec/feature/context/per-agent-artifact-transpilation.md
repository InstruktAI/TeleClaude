---
description: 'Source artifacts render into the shared command corpus and per-agent masters and tier-local skills, with YAML frontmatter and parameter preambles emitted directly by their transforms.'
visibility: 'public'
---

# Per-Agent Artifact Transpilation — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Per-agent artifact transpilation is the Sync step that renders validated
Sources into their deployed form. Two outputs remain per-agent: the
entrypoint master each CLI reads unprompted, emitted per target in that
target's expected shape, and the tier-local skill packages a repository authors
for its own sessions, rendered per target into the native skill directories

because preloading is their purpose. Global skill packages compose into
`~/.teleclaude/skills/`; they produce no per-agent runtime output, and
subagent definitions are not an artifact class at all. No command corpus is
produced: what a session is assigned is a procedure, reached through the
loader message TeleClaude composes at procedure entry
(`local/projects/teleclaude/spec/feature/agent_runtime/procedure-entry`), and
the parameter preamble that loader carries is the procedure entry's, not this
transpiler's. The transpiler serializes YAML frontmatter through the shared
emitter.

## Canonical fields

### Use cases

```
Scenario: Codex output preserves quoted frontmatter values
  Given a source artifact whose frontmatter contains a value with single quotes
  When the transpiler processes the artifact for the Codex target
  Then the shared YAML emitter preserves the frontmatter values
  And the emitted frontmatter is parsable by the upstream Codex YAML parser
  And the artifact is written under the Codex per-agent output directory
```

```
Scenario: Gemini skill is transpiled to Markdown/YAML, not TOML
  Given a source skill artifact with name, description, and parameters
  When the transpiler processes the skill for the Gemini target
  Then the Gemini skill transform delegates to the shared frontmatter emitter
  And the output is Markdown with YAML frontmatter (same shape as the Claude skill output)
  And the "hooks" key is removed from the emitted frontmatter
  And the required source name is checked against the skill folder before emission
```

```
Scenario: UC-PAT4 No target receives a subagent definition; the Gemini target keeps its master and skills only
  Given the source tree carries no subagent definitions, because they are not an artifact class
  When the transpiler processes artifacts for the Gemini target
  Then no agent definition is transpiled to TOML or written under any Gemini output directory
  And tier-local skills continue to use the Markdown/YAML path on the same sync invocation
```

```
Scenario: Missing per-agent output directory is created automatically
  Given the per-agent output directory for the Codex target does not exist
  When the transpiler is asked to write a Codex artifact
  Then the directory is created as needed
  And the artifact is written to the new directory
  And no error is raised for the missing parent path
```

#### UC-PAT1: A skill package retains its upstream structure

```gherkin
Scenario: An agent synchronizes a skill package with upstream-authored structure
  Given an agent authors a skill package with valid identity metadata
  And its Markdown does not follow TeleClaude's normalized skill section taxonomy
  When the agent synchronizes the skill
  Then the package body produces no taxonomy-validation finding
  And inline directives and agent tokens are rendered through the normal pipeline
  And the package keeps the source folder's name wherever it is emitted
```

#### UC-PAT2: Only tier-local skill packages are emitted per target

```gherkin
Scenario: Per-target skill emission is limited to tier-local packages
  Given a repository publishes one global skill package and authors one tier-local skill package for its own sessions
  When sync renders skills for the enabled runtimes
  Then the tier-local package is emitted under its folder name into each enabled runtime's native skill directory at that repository's root
  And the global package is composed into the TeleClaude skills home only and is emitted into no runtime's skill directory
  And neither package is emitted into a runtime's user-global skill directory
  And every other skill-rendering rule applies identically to both packages
```

#### UC-PAT5: Generated artifacts require no external Markdown formatter

### Cross-context references

- **agent_runtime** — Each downstream agent CLI consumes two TeleClaude
  outputs: its entrypoint master, in that CLI's expected shape, and any
  tier-local skills materialized into its native skill directory. Commands
  and global skills are not consumed as runtime artifacts by any CLI —
  sessions read command documents from the shared corpus when the composed
  loader names one, and global skills are discovered through the TeleClaude
  skills home the master points at.

## Known caveats

- Skill folders are the runtime identity, and every source `SKILL.md` must declare
  the same `name` plus a non-empty `description`. An upstream heading taxonomy is
  always preserved. Target transforms emit the package under its folder name.
- Token substitution (`{AGENT_PREFIX}`, `{{agent}}`) happens at the body
  level only — source authors cannot reference the prefix inside frontmatter.
- Per-agent output directory creation is silent; operators reviewing a diff
  cannot infer from new directories whether a project was freshly added or
  simply re-synced.
