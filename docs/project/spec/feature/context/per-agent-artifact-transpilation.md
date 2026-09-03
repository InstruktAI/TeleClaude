---
description: 'Source artifacts (agents/commands/skills) are transformed per target agent — Claude/Codex get YAML frontmatter; Gemini commands and agents get TOML; Gemini skills get Markdown/YAML — with parameter preamble injection and Codex-specific frontmatter escaping.'
visibility: 'public'
---

# Per-Agent Artifact Transpilation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

<!-- planned-change:command-loader-and-title-cutover -->

Per-agent artifact transpilation is the Sync step that converts validated
Source artifacts (commands, skills, and agent definitions) into the format
each downstream agent CLI expects. Claude and Codex receive Markdown with
YAML frontmatter for every artifact kind. Gemini splits by kind: Gemini
commands and agents are converted to TOML, while Gemini skills stay in
Markdown with YAML frontmatter via the shared frontmatter emitter (the same
path used by Claude, with the `hooks` key explicitly stripped). The
transpiler also rewrites parameter metadata from frontmatter into an
HTML-comment preamble at the top of the body so the target agent's parser
sees the shape it understands, and it applies a Codex-specific frontmatter
escape to work around an upstream parser bug.

<!-- change:command-loader-and-title-cutover -->

Per-agent artifact transpilation is the Sync step that renders validated
Sources into their deployed form. Two outputs remain per-agent: the
entrypoint master each CLI reads unprompted, emitted per target in that
target's expected shape, and tier-local skill packages from `.agents/skills/`,
rendered per target into the native skill directories because preloading is
their purpose. Command artifacts normalize into the shared corpus under
`~/.teleclaude/commands/` and global skill packages compose into
`~/.teleclaude/skills/`; neither produces per-agent runtime output, and
subagent definitions are not an artifact class at all. Sessions
reach a corpus document through the loader message TeleClaude composes at
dispatch, not through a runtime artifact. The transpiler rewrites command
parameter metadata from frontmatter into an HTML-comment preamble in the
corpus document so the loading agent sees the shape it understands, and it
keeps target-specific transforms such as the Codex single-quote escape on the
master.

<!-- /planned-change:command-loader-and-title-cutover -->

## Canonical fields

### Use cases

```
<!-- planned-change:command-loader-and-title-cutover -->
Scenario: Claude target receives YAML frontmatter with parameter preamble injection
  Given a source command artifact with a "parameters" field in its frontmatter
  When the transpiler processes the artifact for the Claude target
  Then the frontmatter emitter renders YAML frontmatter without the "parameters" field
  And the parameter-preamble injector renders an HTML-comment block describing parameters at the top of the body
  And the body's {AGENT_PREFIX} and {{agent}} tokens are substituted with Claude's prefix
  And the transpiled artifact is written under the Claude per-agent output directory
<!-- change:command-loader-and-title-cutover -->
Scenario: TeleClaude command source is written to the shared command corpus
  Given a source command artifact with a "parameters" field in its frontmatter
  When the transpiler processes command artifacts for any target set
  Then the frontmatter emitter renders a normalized Markdown command document without the "parameters" field
  And the parameter-preamble injector renders an HTML-comment block describing parameters at the top of the body
  And the normalized command document is written to the shared TeleClaude command corpus
  And no per-agent output of any kind is written for the command artifact
<!-- /planned-change:command-loader-and-title-cutover -->
```

```
Scenario: Codex output escapes single-quoted scalars in frontmatter
  Given a source artifact whose frontmatter contains a value with single quotes
  When the transpiler processes the artifact for the Codex target
  Then the Codex frontmatter escape rewrites single-quote scalars
  And the emitted frontmatter is parsable by the upstream Codex YAML parser
  And the artifact is written under the Codex per-agent output directory
```

<!-- planned-change:drop-skill-taxonomy-optin -->
```
Scenario: Gemini skill is transpiled to Markdown/YAML, not TOML
  Given a source skill artifact with name, description, and parameters
  When the transpiler processes the skill for the Gemini target
  Then the Gemini skill transform delegates to the shared frontmatter emitter
  And the output is Markdown with YAML frontmatter (same shape as the Claude skill output)
  And the "hooks" key is removed from the emitted frontmatter
  And the parameters preamble is rendered into the body as HTML comments
  And the required source name is checked against the skill folder before emission
  And teleclaude_taxonomy is stripped from emitted frontmatter when present
```
<!-- change:drop-skill-taxonomy-optin -->
```
Scenario: Gemini skill is transpiled to Markdown/YAML, not TOML
  Given a source skill artifact with name, description, and parameters
  When the transpiler processes the skill for the Gemini target
  Then the Gemini skill transform delegates to the shared frontmatter emitter
  And the output is Markdown with YAML frontmatter (same shape as the Claude skill output)
  And the "hooks" key is removed from the emitted frontmatter
  And the parameters preamble is rendered into the body as HTML comments
  And the required source name is checked against the skill folder before emission
```
<!-- /planned-change:drop-skill-taxonomy-optin -->

```
<!-- planned-change:command-loader-and-title-cutover -->
Scenario: Gemini command/agent is transpiled to TOML
  Given a source command or agent artifact (not a skill) targeting Gemini
  When the transpiler processes the artifact for the Gemini target
  Then the Gemini command/agent transform converts the frontmatter and body into a TOML representation
  And the TOML output is written under Gemini's per-agent output directory
  And skills continue to use the Markdown/YAML path on the same sync invocation
<!-- change:command-loader-and-title-cutover -->
Scenario: No target receives a subagent definition; the Gemini target keeps its master and skills only
  Given the source tree carries no subagent definitions, because they are not an artifact class
  When the transpiler processes artifacts for the Gemini target
  Then no agent definition is transpiled to TOML or written under any Gemini output directory
  And source command artifacts are written to the shared TeleClaude command corpus, not a Gemini command output directory
  And tier-local skills continue to use the Markdown/YAML path on the same sync invocation
<!-- /planned-change:command-loader-and-title-cutover -->
```

```
Scenario: Missing per-agent output directory is created automatically
  Given the per-agent output directory for the Codex target does not exist
  When the transpiler is asked to write a Codex artifact
  Then the directory is created as needed
  And the artifact is written to the new directory
  And no error is raised for the missing parent path
```

<!-- planned-change:drop-skill-taxonomy-optin -->
```
Scenario: Skill packages retain upstream structure through the runtime renderer
  Given a skill package exists under agents/skills/<name>/ or .agents/skills/<name>/
  And its Markdown does not follow TeleClaude's normalized skill section taxonomy
  When the transpiler processes the skill for any target agent
  Then the entrypoint's name, description, and folder identity are validated
  And body taxonomy validation runs only when SKILL.md declares teleclaude_taxonomy: true
  And inline directives and agent tokens are rendered through the normal pipeline
  And the skill is emitted under the source folder's name for each target agent
```
<!-- change:drop-skill-taxonomy-optin -->
#### UC-PAT1: A skill package retains its upstream structure

```gherkin
Scenario: An agent synchronizes a skill package with upstream-authored structure
  Given an agent authors a skill package with valid identity metadata
  And its Markdown does not follow TeleClaude's normalized skill section taxonomy
  When the agent synchronizes the skill for a supported runtime
  Then the package body produces no taxonomy-validation finding
  And inline directives and agent tokens are rendered through the normal pipeline
  And the skill is emitted under the source folder's name
```
<!-- /planned-change:drop-skill-taxonomy-optin -->

<!-- planned:command-loader-and-title-cutover -->

#### UC-PAT2: Only tier-local skill packages are emitted per target

```gherkin
Scenario: Per-target skill emission is limited to tier-local packages
  Given a global skill package under agents/skills/<name>/ and a tier-local skill package under .agents/skills/<name>/
  When sync renders skills for the enabled runtimes
  Then the tier-local package is emitted under its folder name into each enabled runtime's native skill directory
  And the global package is composed into the TeleClaude skills home only and is emitted into no runtime's skill directory
  And every other skill-rendering rule applies identically to both packages
```

<!-- /planned:command-loader-and-title-cutover -->

### Cross-context references

<!-- planned-change:command-loader-and-title-cutover -->

- **agent_runtime** — Each downstream agent CLI is the consumer of its
  transpiled format. Claude and Codex parse YAML frontmatter for every
  artifact kind. Gemini parses TOML for commands and agents and Markdown
  with YAML frontmatter for skills. All three read the parameter preamble
  from the body.

<!-- change:command-loader-and-title-cutover -->

- **agent_runtime** — Each downstream agent CLI consumes two TeleClaude
  outputs: its entrypoint master, in that CLI's expected shape, and any
  tier-local skills materialized into its native skill directory. Commands
  and global skills are not consumed as runtime artifacts by any CLI —
  sessions read command documents from the shared corpus when the composed
  loader names one, and global skills are discovered through the TeleClaude
  skills home the master points at.

<!-- /planned-change:command-loader-and-title-cutover -->

## Known caveats

- The Codex single-quote escape is a transitive workaround for the upstream
  bug filed as `openai/codex#11495`. If Codex fixes its parser upstream,
  this normalization step becomes vestigial — but removing it requires
  verifying the fixed parser is in the Codex version every operator has
  installed.
- Skill folders are the runtime identity, and every source `SKILL.md` must declare
  the same `name` plus a non-empty `description`. An upstream heading taxonomy is
  preserved unless the entrypoint opts into TeleClaude's taxonomy. Target transforms
  emit the package under its folder name and omit the build-only opt-in field.
- The parameter preamble is injected into the artifact body as HTML comments;
  it is NOT preserved in frontmatter. Downstream consumers that read the
  Deployed artifact as YAML/TOML alone will NOT see `parameters` — they must
  also parse the body preamble.
- Token substitution (`{AGENT_PREFIX}`, `{{agent}}`) happens at the body
  level only — source authors cannot reference the prefix inside frontmatter.
- Per-agent output directory creation is silent; operators reviewing a diff
  cannot infer from new directories whether a project was freshly added or
  simply re-synced.
