---
description: 'Source artifacts render into per-agent masters and tier-local skills with YAML frontmatter; procedure-entry owns parameter preambles.'
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

#### UC-PAT1: A skill package retains its upstream structure

#### UC-PAT2: Only tier-local skill packages are emitted per target

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
