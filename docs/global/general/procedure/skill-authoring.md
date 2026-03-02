---
id: 'general/procedure/skill-authoring'
type: 'procedure'
scope: 'global'
description: 'Create skills as thin wrappers around doc snippets, with optional scripts for deterministic tooling.'
---

# Skill Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/spec/agent-artifacts.md
- @~/.teleclaude/docs/general/procedure/agent-artifact-authoring.md

## Goal

Create a skill that follows the agent-artifact schema and leverages existing doc snippets as the knowledge layer.

## Preconditions

- The knowledge the skill needs to convey exists (or will be created) as doc snippets.
- The agent-artifacts spec is available for the skill schema.

## Steps

1. **Examine existing skills.** Read 2-3 skills in `agents/skills/` to learn the pattern before creating a new one. Skills are thin wrappers — they define Purpose, Scope, Inputs, Outputs, and Procedure, but delegate the actual knowledge to doc snippets via Required reads.

2. **Identify the knowledge source.** Determine which doc snippet(s) contain the procedure or spec the skill will wrap. If no snippet exists yet, create it first using the doc-snippet-authoring procedure. The doc snippet is the knowledge; the skill is the activation interface.

3. **Decide if scripts are needed.** Scripts belong in a skill only when they provide deterministic tooling that a model cannot reliably generate from training — binary format manipulation, scaffolding with specific directory structures, validation against a schema. If the skill is pure procedural knowledge, it needs no scripts.

4. **Create the skill directory** at `agents/skills/{skill-name}/`.

5. **Write SKILL.md** following the agent-artifact schema:
   - Frontmatter: `name`, `description` (when to use the skill).
   - `# {Skill Name}` — single H1.
   - `## Required reads` — point to the doc snippet(s) that carry the knowledge.
   - `## Purpose` — one or two sentences.
   - `## Scope` — when and where to apply.
   - `## Inputs` — what the skill needs to start.
   - `## Outputs` — what it produces.
   - `## Procedure` — a brief line referencing the required reads, or a compact inline procedure if short enough. Do not duplicate content that already exists in doc snippets.
   - `## Examples` (optional) — only when concrete usage clarifies.

6. **Add scripts if applicable** under `scripts/`. Scripts must be standalone, executable, and self-documenting.

7. **Run `telec sync`** to compile and deploy the skill.

8. **Verify** the skill appears in the skill list and triggers correctly.

## Outputs

- A skill in `agents/skills/{skill-name}/` with SKILL.md and optional scripts.
- Compiled and deployed via `telec sync`.

## Recovery

- If `telec sync` fails, fix the issue and rerun.
- If the skill duplicates content from doc snippets, remove the duplication and reference via Required reads instead.
