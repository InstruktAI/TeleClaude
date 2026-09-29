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
  - Frontmatter: `description`, optional `argument-hint`, optional `parameters`, optional `hooks` (emitted for Claude Code outputs only)
  - Body: normalized command schema (see below)
  - Retirement companion: a zero-byte sibling `<name>.<slug>.md` marks the command retired by the delivering `<slug>`. Validation accepts it in place of a command, distribution emits nothing for it and keeps deploying the command, and the delivery fold deletes both (`general/policy/agent-artifact-governance`).

- **Skills**:
  - Frontmatter: required `name` and `description`
  - Identity: `name` must equal the containing folder in every skill package
  - Body: pass-through; never graded against TeleClaude's artifact taxonomy

## Allowed values

- `description`: short, imperative summary.
- `argument-hint`: optional string for CLI argument hints (commands).
- `hooks`: optional (commands). Passed through verbatim to Claude Code outputs and
  omitted from every other runtime's output; its shape is the target runtime's hook
  schema and TeleClaude does not validate it.
- `name`: identifier used for artifact lookup. A skill's folder is its runtime
  identity, so its required source `name` must equal that folder.

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
  Discipline section is the behavioral anchor: it names this command's own
  failure mode — the mistake an agent is most likely to make at the moment of
  acting — and the rule that prevents it. A caution that would fit any command
  is not a Discipline. It stays short enough to be the last thing read before
  acting; its measure is specificity, never length. It does not duplicate the
  procedure. It activates awareness of the
  procedure at the moment it matters most. Every command must have one. A command
  without a Discipline section ships without its safety net. When a command
  delegates to its counterpart procedure's discipline, that procedure must
  define `## Discipline`; the reference reinforces but never replaces the
  command's own command-specific anchor.

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

The `SKILL.md` body and every supporting Markdown resource retain their upstream
structure and are not checked against any section taxonomy. The universal `name`,
`description`, and folder-identity contract applies to the entrypoint.

## Known caveats

- Normalized commands use the declared command frontmatter. Skill packages may
  carry upstream fields in addition to the universal identity fields.
- Skill bodies are pass-through in both scopes. Supporting Markdown is always
  opaque to taxonomy validation. Every package uses the same rendering and
  target-transformation pipeline.
- Scope is conveyed by location, mirroring `docs/{global,project}`:
  - **Global scope**: `<repository>/agents/global/commands/<domain>/*.md` for a domain the repository publishes; `TeleClaude/agents/global/commands/general/*.md` and `TeleClaude/agents/global/skills/*/SKILL.md` from the mother alone
  - **Project scope**: `<project>/agents/project/commands/*.md`, `<project>/agents/project/skills/*/SKILL.md`
  - `.agents/` is a delivery location and is never read as a source
- Keep prompts concise to avoid bloated agent context.
- Required reads in source docs are **inlined** in generated outputs; `@` references
  are transformed into inline content and do not appear in emitted files. A
  `## Required reads` ref is **hoisted** to the top of the compiled artifact. To
  land a snippet at a specific point in the body instead — adjacent to the step
  that needs it — place an `@include` directive (`@include: <path>` inside an HTML
  comment) at that point rather than filing the ref under Required reads.

### Runtime support matrix

Commands never reach a runtime home: they compose to the global command corpus
and are reached through the loader message composed at dispatch. Global skills
compose to the catalog and reach no runtime home either. What a runtime receives
natively is its entrypoint master and the tier-local skills of the root it runs
in; the mother's deployment contract owns the per-runtime locations.

- **Claude Code**: entrypoint master, tier-local skills, `hooks` frontmatter honored
- **Codex CLI**: entrypoint master, tier-local skills; `hooks` not emitted
- **Gemini CLI**: entrypoint master, tier-local skills; `hooks` not emitted
