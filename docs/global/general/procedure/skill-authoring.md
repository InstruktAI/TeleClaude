---
id: 'general/procedure/skill-authoring'
type: 'procedure'
scope: 'global'
description: 'Gate and create skills. A skill is warranted only when it carries scripts — deterministic tooling a model cannot generate on demand.'
---

# Skill Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/artifact-scope.md
- @~/.teleclaude/docs/general/spec/agent-artifacts.md
- @~/.teleclaude/docs/general/procedure/agent-artifact-authoring.md

## Goal

Determine whether a skill is warranted, and if so, create one that follows the agent-artifact schema.

## Preconditions

- A request to create a skill, or a capability that might need one.
- The agent-artifacts spec is available for the skill schema.

## Steps

1. **Gate: does this need scripts?** A skill exists solely to bundle executable automation next to its instructions. Scripts mean deterministic tooling a model cannot reliably generate from training data — binary format manipulation, scaffolding with exact directory structures, validation against a schema, CLI wrappers around external tools. If the answer is no — the capability is pure procedural knowledge — do not create a skill. Instead: create a doc snippet using the doc-snippet-authoring procedure (scope per the artifact-scope policy), add it to the appropriate baseline index so it is progressively disclosed on load, and tell the requester why a skill was not created. Stop here.

2. **Verify the script is not trivially replaceable.** If the script could be replaced by an inline shell command an agent could write on demand (e.g., `cp template.html output/`, `mkdir -p foo/bar`), the script adds no value. Follow the same redirect as step 1. Stop here.

3. **Identify the knowledge source.** Determine which doc snippet(s) contain the procedure or spec the skill will wrap. If no snippet exists yet, create it first. The doc snippet is the knowledge; the skill is the activation interface for the scripts.

4. **Examine existing skills.** Read 1-2 skills in `agents/skills/` to confirm the pattern before creating a new one.

5. **Create the skill directory** at `agents/skills/{skill-name}/`.

6. **Write SKILL.md** following the agent-artifact schema:
   - Frontmatter: `name`, `description` (when to use the skill).
   - `# {Skill Name}` — single H1.
   - `## Required reads` — point to the doc snippet(s) that carry the knowledge.
   - `## Purpose` — one or two sentences.
   - `## Scope` — when and where to apply.
   - `## Inputs` — what the skill needs to start.
   - `## Outputs` — what it produces.
   - `## Procedure` — a brief line referencing the required reads, plus how to invoke the scripts.

7. **Add scripts** under `scripts/`. Scripts must be standalone, executable, and self-documenting.

8. **Run `telec sync`** to compile and deploy the skill.

9. **Verify** the skill appears in the skill list and triggers correctly.

## Outputs

- A skill in `agents/skills/{skill-name}/` with SKILL.md and `scripts/`.
- Compiled and deployed via `telec sync`.

## Recovery

- If `telec sync` fails, fix the issue and rerun.
- If the gate was skipped and a scriptless skill was created, remove the skill and migrate its content to a doc snippet.
