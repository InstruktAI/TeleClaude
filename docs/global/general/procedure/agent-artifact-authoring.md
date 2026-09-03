---
activation_trigger: Use when creating, changing, proposing, or drafting an agent, skill,
  or command first enters consideration — before its shape is decided.
description: Establish whether agent-artifact work is ready and authorized, then author
  artifacts that compile into tool-specific formats.
visibility: public
---

# Agent Artifact Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/artifact-scope.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Establish authority and convergence before materializing agent instructions,
then create or update artifacts that follow the schema and compile correctly
for supported CLIs.

## Preconditions

- Artifact schema references are available.
- Target repository includes global or project artifact scopes.
- Authoring authority established in Step 0.

## Steps

0. **Establish authoring authority.** Load this procedure when an agent artifact
   first enters consideration, before drafting its shape. A bounded dispatched
   brief or an original explicit authoring request supplies authority for its
   scope. When the current human conversation began as exploration or design,
   authoring starts only after every active participant agrees the outcome and
   the human releases it for materialization. Silence, unilateral confidence,
   partial agreement, and automated checkpoint or approval output supply none.
   Until the gate opens, keep forming work in conversation or a
   non-authoritative scratchpad and stop before editing Git-tracked artifacts on
   shared `main`.
1. Choose the artifact type (agent, skill, command, or AGENTS.md). Third-party skill
   packages are incorporated rather than authored; follow
   `general/procedure/skill-management` for those.
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
9. After the authorized artifact batch is stable, run `telec sync`. This step
   supplies neither authoring nor commit authority.

## Outputs

- Updated artifact files in the selected scope.
- Updated generated artifacts in tool-specific output folders.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.

## See Also

- ~/.teleclaude/docs/general/spec/tools/telec-cli.md
