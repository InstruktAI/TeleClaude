---
activation_trigger: About to create or edit an agent, skill, or command definition
  under agents/ or .agents/.
description: Author agent artifacts (agents, skills, commands) that compile into tool-specific
  formats.
visibility: public
---

# Agent Artifact Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/artifact-scope.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Create or update agent artifacts that follow the schema and compile correctly for supported CLIs.

## Preconditions

- Artifact schema references are available.
- Target repository includes global or project artifact scopes.

## Steps

1. Choose the artifact type (agent, skill, command, or AGENTS.md).
2. Follow the corresponding schema and taxonomy requirements.
3. Ensure frontmatter fields are complete and consistent (except AGENTS.md, which has none).
4. If the command takes multiple arguments, declare `parameters` in frontmatter
   as an ordered list with `name` and optional `required`/`default` per entry.
   List order defines position. Use `$name` references in the body. See the
   agent-artifacts spec for the full schema.
5. Add the artifact title (`# ...`) for all artifacts.
6. Apply the artifact-specific schema from the agent-artifacts spec.
7. **Keep commands thin; Inputs/Outputs are conditional.** A command is a session
   entry point — who am I, what do I know, what did I receive — not a procedure manual.
   It carries only `## Purpose` (one sentence), `## Required reads` (its governing
   procedure + role), `## Steps` (mechanical invocation), and `## Discipline`. It MUST
   NOT declare `## Inputs` or `## Outputs` when a counterpart procedure governs its work:
   the argument lives in frontmatter (`argument-hint`/`parameters`) and the outputs in
   the procedure's `## Outputs`. Add Inputs/Outputs ONLY to a self-contained command that
   has no such counterpart. This is a judgement, not a machine check — listing several
   procedures for context is not the same as having one that owns your inputs and outputs.
8. **ADR discipline (decision capture).** Artifacts describe the _current behavior_; they hold no reasoning logs. An ADR is reserved for a real, contestable decision and the default is none — consult `general/policy/adr-discipline` for the bar before writing one.
9. After any doc change, run `telec sync`.

## Outputs

- Updated artifact files in the selected scope.
- Updated generated artifacts in tool-specific output folders.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.

## See Also

- ~/.teleclaude/docs/general/spec/tools/telec-cli.md
