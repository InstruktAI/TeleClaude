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
  - Frontmatter: required `name` and `description`; optional
    `teleclaude_taxonomy: true` opts the entrypoint into the normalized body schema
  - Identity: `name` must equal the containing folder in every skill package
  - Body: pass-through by default; normalized skill schema only when
    `teleclaude_taxonomy: true`
- **Agents**:
  - Frontmatter: `name`, `description`, optional tool and permission fields
  - Body: normalized agent schema (see below)
- **Hooks**:
  - Frontmatter and body follow the target runtime’s hook schema

## Allowed values

- `description`: short, imperative summary.
- `argument-hint`: optional string for CLI argument hints (commands).
- `name`: identifier used for artifact lookup. A skill's folder is its runtime
  identity, so its required source `name` must equal that folder.
- `teleclaude_taxonomy`: optional boolean for skill entrypoints. Only `true`
  activates the TeleClaude body, section, Required-reads, inline-reference, and
  See Also contract. It is build-only metadata and is stripped from emitted
  runtime frontmatter. The field is optional at the package boundary because
  incorporated third-party packages retain their upstream body; every first-party
  skill created through the skill-authoring procedure declares it `true`.
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

### Skills with `teleclaude_taxonomy: true`

1. `# <Skill Name>`
2. `## Required reads` (only if needed)
3. `## Purpose`
4. `## Scope`
5. `## Inputs`
6. `## Outputs`
7. `## Procedure`
8. `## See Also` (only if needed; must be last)

Without `teleclaude_taxonomy: true`, the `SKILL.md` body and every supporting
Markdown resource retain their upstream structure and are not checked against
this section taxonomy. The universal `name`, `description`, and folder-identity
contract still applies to the entrypoint.

### Agents

1. `# <Agent Name>`
2. `## Required reads` (only if needed)
3. Activation line: `You are now the <Role>.`
4. `## Purpose`
5. `## Scope`
6. `## Inputs`
7. `## Outputs`
8. `## Procedure`

All normalized sections are mandatory for agents and opted-in skills; only the
explicitly identified sections above are optional. If content does not fit the
normalized sections, it should not be included in those artifacts.

## Known caveats

- Normalized commands use the declared command frontmatter. Skill packages may
  carry upstream fields in addition to the universal identity fields.
- Skill bodies are pass-through in both scopes unless their `SKILL.md` explicitly
  declares `teleclaude_taxonomy: true`. Supporting Markdown is always opaque to
  taxonomy validation. Both kinds use the same rendering and target-transformation
  pipeline.
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

No agent runtime receives native per-command artifacts. TeleClaude command documents
deploy once to the shared corpus at `~/.teleclaude/commands/` and every runtime invokes
them through the singular TeleClaude command skill. In runtimes where a skill is itself a
slash command, that skill is the command surface.

- **Claude Code**
  - Skills, Agents, Hooks
  - Outputs: `~/.claude/` (global/project runtime artifacts) plus `~/.teleclaude/commands/` (shared command corpus)
- **Codex CLI**
  - Skills
  - No Hooks, no Agents. Custom prompts are vendor-deprecated in favour of skills.
  - Outputs: `~/.codex/` (global/project runtime artifacts) plus `~/.teleclaude/commands/` (shared command corpus)
- **Antigravity CLI (`agy`)**
  - Skills, Hooks
  - No Agents. `agy` has no custom-commands directory; skills supersede it, and a
    user-global skill is imported as a slash command at launch.
  - Instruction files are resolved through the configured `context.fileName`
    (`AGENTS.md`), not a global master file.
  - Outputs: `~/.gemini/antigravity-cli/` (global runtime artifacts) and `.agents/`
    (workspace scope) plus `~/.teleclaude/commands/` (shared command corpus)
  - The legacy Node Gemini CLI layout (`~/.gemini/commands/`, `~/.gemini/skills/`,
    `~/.gemini/agents/`, `~/.gemini/GEMINI.md`) is obsolete and is not provisioned.

<!-- /planned-change:command-migration-to-singular-telec-skill -->
