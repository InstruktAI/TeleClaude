# Agent Artifacts Quickstart

Required reads

@~/.teleclaude/docs/baseline/reference/agent-artifacts.md
@~/.teleclaude/docs/software-development/concept/agent-artifact-distribution.md

## Goal

Create agent artifacts in a repo so they are discoverable and distributable
across supported agent runtimes.

## Steps

1. Create an agent, skill, or command using the canonical paths:
   - `agents/<name>.md`
   - `skills/<skill-name>/SKILL.md`
   - `commands/<name>.md`
2. Add frontmatter using the appropriate schema and write concise intent.
3. Keep artifacts focused; split when intent becomes multi-purpose.
4. Let the watcher/build step generate runtime-specific outputs.

## Outputs

- Source artifacts exist with valid metadata.
- Generated artifacts are produced for each runtime.

## Recovery

- If an artifact is not discovered, validate its frontmatter fields.
- If selection is poor, rewrite `description` to be task- and outcome-focused.
