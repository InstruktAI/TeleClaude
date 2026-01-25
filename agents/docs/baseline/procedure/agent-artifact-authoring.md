# Agent Artifact Authoring — Procedure

Required reads

@~/.teleclaude/docs/baseline/procedure/snippet-authoring-sequence.md
@~/.teleclaude/docs/baseline/policy/referencing-doc-snippets.md
@~/.teleclaude/docs/baseline/reference/agent-artifacts.md

## Goal

Author agent artifacts (agents, skills, commands) in a consistent structure so
watchers can discover and distribute them to supported agent runtimes.

## Preconditions

- Project has `agents/`, `skills/`, or `commands/` folders.
- `AGENTS.md` includes baseline references.

## Steps

1. Choose the artifact type (agent, skill, or command).
2. Create the artifact file in the canonical path:
   - Agent: `agents/<name>.md`
   - Skill: `skills/<skill-name>/SKILL.md`
   - Command: `commands/<name>.md`
3. Add frontmatter using the schema for that artifact type.
4. Write concise body instructions focused on intent and execution.
5. Ensure descriptions are selection-friendly and task-focused.
6. Place optional supporting material in sibling folders (e.g., `references/`,
   `examples/`, `scripts/`, `assets/`).

## Outputs

- Artifact files exist with valid frontmatter and clear instructions.
- Metadata is precise enough for accurate selection.

## Recovery

- If metadata is vague, rewrite description to state when to use the artifact.
- If a file grows too broad, split into multiple focused artifacts.
