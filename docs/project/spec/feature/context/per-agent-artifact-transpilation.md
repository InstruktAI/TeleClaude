---
id: 'project/spec/feature/context/per-agent-artifact-transpilation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Source artifacts (agents/commands/skills) are transformed per target agent — Claude/Codex get YAML frontmatter; Gemini commands and agents get TOML; Gemini skills get Markdown/YAML — with parameter preamble injection and Codex-specific frontmatter escaping.'
---

# Per-Agent Artifact Transpilation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

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

## Canonical fields

### Use cases

```
Scenario: Claude target receives YAML frontmatter with parameter preamble injection
  Given a source command artifact with a "parameters" field in its frontmatter
  When the transpiler processes the artifact for the Claude target
  Then the frontmatter emitter renders YAML frontmatter without the "parameters" field
  And the parameter-preamble injector renders an HTML-comment block describing parameters at the top of the body
  And the body's {AGENT_PREFIX} and {{agent}} tokens are substituted with Claude's prefix
  And the transpiled artifact is written under the Claude per-agent output directory
```

```
Scenario: Codex output escapes single-quoted scalars in frontmatter
  Given a source artifact whose frontmatter contains a value with single quotes
  When the transpiler processes the artifact for the Codex target
  Then the Codex frontmatter escape rewrites single-quote scalars
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
  And the parameters preamble is rendered into the body as HTML comments
  And the skill's name matches its folder name or the transpile fails before any output is written
```

```
Scenario: Gemini command/agent is transpiled to TOML
  Given a source command or agent artifact (not a skill) targeting Gemini
  When the transpiler processes the artifact for the Gemini target
  Then the Gemini command/agent transform converts the frontmatter and body into a TOML representation
  And the TOML output is written under Gemini's per-agent output directory
  And skills continue to use the Markdown/YAML path on the same sync invocation
```

```
Scenario: Missing per-agent output directory is created automatically
  Given the per-agent output directory for the Codex target does not exist
  When the transpiler is asked to write a Codex artifact
  Then the directory is created as needed
  And the artifact is written to the new directory
  And no error is raised for the missing parent path
```

```
Scenario: Skill folder name mismatch fails before write
  Given a skill source whose folder name does not match its frontmatter "name" field
  When the transpiler processes the skill for any target agent
  Then transpilation fails with a name-mismatch error
  And no per-agent output is written for this skill
```

### Cross-context references

- **agent_runtime** — Each downstream agent CLI is the consumer of its
  transpiled format. Claude and Codex parse YAML frontmatter for every
  artifact kind. Gemini parses TOML for commands and agents and Markdown
  with YAML frontmatter for skills. All three read the parameter preamble
  from the body.

## Known caveats

- The Codex single-quote escape is a transitive workaround for the upstream
  bug filed as `openai/codex#11495`. If Codex fixes its parser upstream,
  this normalization step becomes vestigial — but removing it requires
  verifying the fixed parser is in the Codex version every operator has
  installed.
- Skill `name` validation is enforced at transpile time: the source folder
  name must match the frontmatter `name` field, or transpilation fails before
  any output is written. There is no auto-correct or warn-only mode.
- The parameter preamble is injected into the artifact body as HTML comments;
  it is NOT preserved in frontmatter. Downstream consumers that read the
  Deployed artifact as YAML/TOML alone will NOT see `parameters` — they must
  also parse the body preamble.
- HTML-comment context-preservation markers
  (`<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->` and `_END`) wrap skill
  blocks and are round-trip-safe for v1↔v2 source migration. Tools that
  rewrite artifact bodies must preserve these markers verbatim.
- Token substitution (`{AGENT_PREFIX}`, `{{agent}}`) happens at the body
  level only — source authors cannot reference the prefix inside frontmatter.
- Per-agent output directory creation is silent; operators reviewing a diff
  cannot infer from new directories whether a project was freshly added or
  simply re-synced.
