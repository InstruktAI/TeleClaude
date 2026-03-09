---
id: 'general/spec/agent-artifacts'
type: 'spec'
scope: 'global'
description: 'Minimal schema used for agent artifacts (commands and skills).'
---

# Agent Artifacts — Spec

## What it is

Defines the normalized artifact formats we author and how they map to each supported
agent runtime. This doc is the concrete reference for what exists, what is emitted,
and where those outputs land.

## Canonical fields

- **Commands**:
  - Frontmatter: `description`, optional `argument-hint`, optional `parameters`
  - Body: normalized command schema (see below)
- **Skills**:
  - Frontmatter: `name`, `description`
  - Body: normalized skill schema (see below)
- **Agents**:
  - Frontmatter: `name`, `description`, optional tool and permission fields
  - Body: normalized agent schema (see below)
- **Hooks**:
  - Frontmatter and body follow the target runtime’s hook schema

## Allowed values

- `description`: short, imperative summary.
- `argument-hint`: optional string for CLI argument hints (commands).
- `name`: identifier used for skill/agent lookup; must match the skill folder name.
- `parameters`: optional list of named parameter declarations (commands). Each entry
  has `name` (string), optional `required` (bool), and optional `default` (string).
  Position is implicit from list order (first entry = position 0). At compile time,
  the distribution pipeline injects an HTML-comment preamble mapping parameter names
  to positions. The body references parameters as `$name` — no runtime substitutes
  these; the model interprets them via the preamble. The `parameters` field is
  stripped from emitted frontmatter.

No free text is allowed between the H1 title and the first schema section.
If required reads are needed, place a `## Required reads` section immediately after
the H1 title, ordered from general to concrete: concept → principle → policy → procedure
→ design → spec. After required reads, use the schema below for each artifact type.

### Commands

1. `# <Command Name>`
2. `## Required reads` (only if needed)
3. Activation line: `You are now the <Role>.`
4. `## Purpose`
5. `## Inputs`
6. `## Outputs`
7. `## Steps`
8. `## Examples` (optional)

#### Command content contract

Commands are thin wrappers — session entry points, not procedure manuals. A command
answers three questions: who am I, what do I know, and what did I receive. The
procedure handles the rest.

**What belongs in each section:**

- **Required reads**: The procedure that governs this command's work, plus the role
  concept. This is how the agent learns what to do — not from inline steps.
- **Purpose**: One sentence. What this command achieves, not how.
- **Inputs**: Arguments, flags, and what the agent receives. No validation logic.
- **Outputs**: What the agent must produce — report format, files, state changes.
  Describe the shape, not the process of producing it.
- **Steps**: The mechanical invocation sequence only. Parse args, call a CLI command,
  read a file, act on the result. If a step requires judgement, it belongs in the
  procedure, not here.

**What never goes in a command:**

- Decision trees or conditional logic ("if X, then negotiate with Y").
- Behavioral rules or policy fragments (drift allowlists, review criteria).
- Content that duplicates or paraphrases a required-read procedure.
- Rationale for why steps are done in a certain order.

A command that grows beyond ~35 lines is a signal that procedural content has leaked in.
Extract it to the procedure, add the procedure as a required read, and replace the
inline content with a pointer.

#### Named parameters

When a command takes multiple arguments, declare them in frontmatter `parameters`
instead of parsing `$ARGUMENTS` inline. The distribution pipeline injects an
HTML-comment preamble into the compiled output; the body stays identical across
all runtimes.

**Source artifact:**

```yaml
---
description: Build implementation from plan
argument-hint: <slug> [mode]
parameters:
  - name: slug
    required: true
  - name: mode
    default: standard
---
```

**Body references parameters as `$name`:**

```markdown
## Inputs

- Slug: `$slug` (required)
- Mode: `$mode` (default: `standard`)
```

**Compiled output (all runtimes, prepended to body):**

```html
<!-- $slug = argument at position 0 (required) -->
<!-- $mode = argument at position 1 (default: "standard") -->
```

Rules:
- Each parameter must have a unique `name`.
- Position is derived from list order — no explicit position field needed.
- Use `$name` (lowercase, no braces) in the body — no runtime substitutes this;
  the model interprets it via the preamble.
- `$ARGUMENTS` continues to work for single-argument commands; `parameters` is
  only needed when multiple distinct arguments are required.

### Skills

1. `# <Skill Name>`
2. `## Required reads` (only if needed)
3. `## Purpose`
4. `## Scope`
5. `## Inputs`
6. `## Outputs`
7. `## Procedure`
8. `## Examples` (optional)

### Agents

1. `# <Agent Name>`
2. `## Required reads` (only if needed)
3. Activation line: `You are now the <Role>.`
4. `## Purpose`
5. `## Scope`
6. `## Inputs`
7. `## Outputs`
8. `## Procedure`
9. `## Examples` (optional)

### Optional sections (all artifacts)

- `## Limitations` — only when real constraints exist.
- `## Examples` — only when concrete usage is needed.
- `## See Also` — soft references only; no inline `@` references.

Avoid generic `Notes` sections. If content does not fit the mandatory sections
or the optional sections above, it should not be included.

## Known caveats

- Commands and skills share the same minimal frontmatter; do not invent extra fields.
- Scope is conveyed by location:
  - **Global scope**: `TeleClaude/agents/commands/*.md`, `TeleClaude/agents/skills/*/SKILL.md`
  - **Project scope**: `<project>/.agents/commands/*.md`, `<project>/.agents/skills/*/SKILL.md`
- Keep prompts concise to avoid bloated agent context.
- Required reads in source docs are **inlined** in generated outputs; `@` references
  are transformed into inline content and do not appear in emitted files.

### Runtime support matrix

- **Claude Code**
  - Commands, Skills, Agents, Hooks
  - Outputs: `~/.claude/` (global) and `.claude/` (project)
- **Codex CLI**
  - Commands, Skills
  - No Hooks, no Agents
  - Outputs: `~/.codex/` (global) and `.codex/` (project)
- **Gemini CLI**
  - Commands, Skills, Hooks
  - No Agents
  - Outputs: `~/.gemini/` (global) and `.gemini/` (project)
