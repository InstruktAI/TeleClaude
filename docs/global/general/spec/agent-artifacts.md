---
description: 'Minimal schema used for agent artifacts (commands and skills).'
visibility: 'public'
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

<!-- planned:command-migration-to-singular-telec-skill -->

- Runtime exposure: TeleClaude command artifacts compile to the shared command corpus under `~/.teleclaude/commands/`; supported agent CLIs invoke that corpus through the singular TeleClaude command skill rather than one native runtime command per command artifact.

<!-- /planned:command-migration-to-singular-telec-skill -->

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
5. `## Inputs` — **conditional** (see the content contract below)
6. `## Outputs` — **conditional** (see the content contract below)
7. `## Steps`
8. `## Discipline`

#### Command content contract

Commands are thin wrappers — session entry points, not procedure manuals. A command
answers three questions: who am I, what do I know, and what did I receive. The
procedure handles the rest.

**Inputs and Outputs are conditional, not default.** A command MUST NOT declare
`## Inputs` or `## Outputs` when a counterpart procedure governs its work — the
procedure owns them (its `## Preconditions`/`## Outputs`), and repeating them on the
command is duplication. They may appear ONLY on a self-contained command that has no
such counterpart. This rule is not machine-enforced — it is a judgement and cannot be:
a command may list several procedures as required reads for _context_ without any one
of them being the counterpart that owns its inputs and outputs. Apply the judgement;
when a single procedure clearly governs the command's work, that is the counterpart.

**What belongs in each section:**

- **Required reads**: The procedure that governs this command's work, plus the role
  concept. This is how the agent learns what to do — not from inline steps.
- **Purpose**: One sentence. What this command achieves, not how.
- **Inputs** (conditional): Arguments and flags, only on a self-contained command with
  no counterpart procedure. No validation logic. When a counterpart exists, the
  argument lives in frontmatter (`argument-hint`/`parameters`) and the rest in the
  procedure — omit this section.
- **Outputs** (conditional): What the agent must produce — report shape, files, state
  changes — only on a self-contained command. When a counterpart procedure exists, its
  `## Outputs` owns this; omit the section.
- **Steps**: The mechanical invocation sequence only. Parse args, call a CLI command,
  read a file, act on the result. If a step requires judgement, it belongs in the
  procedure, not here.
- **Discipline**: The last thing the agent reads before acting. This section exists
  because of the recency effect: procedures loaded via required reads land at the
  top of context and fade as the window fills with codebase reads, artifact content,
  and analysis. By the time the agent acts, the constraints are far away. The
  Discipline section is the behavioral anchor — 3-5 sentences that name this
  command's specific failure mode and the one or two rules most likely to be
  violated. It does not duplicate the procedure. It activates awareness of the
  procedure at the moment it matters most. Every command must have one. A command
  without a Discipline section ships without its safety net.

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

### Agents

1. `# <Agent Name>`
2. `## Required reads` (only if needed)
3. Activation line: `You are now the <Role>.`
4. `## Purpose`
5. `## Scope`
6. `## Inputs`
7. `## Outputs`
8. `## Procedure`

All sections are mandatory. No optional sections exist. If content does not fit
the mandatory sections, it should not be included.

## Known caveats

- Commands and skills share the same minimal frontmatter; do not invent extra fields.
- Scope is conveyed by location:
  - **Global scope**: `TeleClaude/agents/commands/*.md`, `TeleClaude/agents/skills/*/SKILL.md`
  - **Project scope**: `<project>/.agents/commands/*.md`, `<project>/.agents/skills/*/SKILL.md`
- Keep prompts concise to avoid bloated agent context.
- Required reads in source docs are **inlined** in generated outputs; `@` references
  are transformed into inline content and do not appear in emitted files. A
  `## Required reads` ref is **hoisted** to the top of the compiled artifact. To
  land a snippet at a specific point in the body instead — adjacent to the step
  that needs it — place an `@include` directive (`@include: <path>` inside an HTML
  comment) at that point rather than filing the ref under Required reads.

### Runtime support matrix

<!-- planned-change:command-migration-to-singular-telec-skill -->

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

<!-- change:command-migration-to-singular-telec-skill -->

- **Claude Code**
  - Skills, Agents, Hooks
  - TeleClaude command artifacts deploy to `~/.teleclaude/commands/` and are invoked through the TeleClaude command skill; they are not emitted as one native Claude command per source command.
  - Outputs: `~/.claude/` (global/project runtime artifacts) plus `~/.teleclaude/commands/` (shared command corpus)
- **Codex CLI**
  - Skills
  - No Hooks, no Agents, no native command prompts for TeleClaude command artifacts
  - Outputs: `~/.codex/` (global/project runtime artifacts) plus `~/.teleclaude/commands/` (shared command corpus)
- **Gemini CLI**
  - Skills, Hooks
  - No Agents, no native command prompts for TeleClaude command artifacts
  - Outputs: `~/.gemini/` (global/project runtime artifacts) plus `~/.teleclaude/commands/` (shared command corpus)

<!-- /planned-change:command-migration-to-singular-telec-skill -->
