---
activation_trigger: Use when considering a new skill or slash command, or converting a procedure
  into one.
description: Gate and create skills. A skill is warranted only when it carries scripts
  — deterministic tooling a model cannot generate on demand; script-free capabilities
  become activatable procedures instead.
visibility: public
---

# Skill Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/artifact-scope.md
- @~/.teleclaude/docs/general/spec/agent-artifacts.md
- @~/.teleclaude/docs/general/procedure/agent-artifact-authoring.md

## Goal

Incorporate a third-party skill package without rewriting its authored body, or
create a TeleClaude thin-wrapper skill whose knowledge stays in canonical docs.

## Preconditions

- A request to incorporate, create, or update a skill.
- The artifact-scope policy and agent-artifacts spec are available.

## Steps

1. **Classify the work.** A copied or linked package authored elsewhere is a
   third-party incorporation. A TeleClaude-authored activation interface tied to
   this platform's docs and scripts is a thin wrapper. Do not rewrite a third-party
   package into TeleClaude's taxonomy.

2. **Choose scope.** Apply the artifact-scope policy. A global package is published
   as a named folder under a registered project's `agents/skills/`; folder existence
   is the publication declaration. A project-only package lives under
   `.agents/skills/`.

3. **Incorporate a third-party skill from the global catalog.** Link the selected
   `~/.teleclaude/skills/<name>/` entry into `.agents/skills/<name>/`. Keep the
   package intact and do not add `teleclaude_taxonomy`. Continue at step 10.

4. **Incorporate a third-party skill from the web for one project.** Copy the
   complete upstream package into `.agents/skills/<name>/`. Preserve its body,
   supporting Markdown, scripts, references, and assets. Ensure only the universal
   entrypoint identity contract: `SKILL.md` has non-empty `name` and `description`,
   and `name` equals the folder. Do not add `teleclaude_taxonomy`. Continue at step 10.

5. **Gate a new TeleClaude thin wrapper: does it need scripts?** A first-party skill
   exists to bundle deterministic automation a model cannot reliably generate on
   demand. If the capability is pure procedural knowledge, create an activatable doc
   procedure instead and stop. A trivial inline shell command does not justify a skill.

6. **Identify the knowledge source.** Locate or first author the doc snippets that
   carry the procedure or specification. The docs are the knowledge; the skill is a
   thin activation interface for those docs and its scripts.

7. **Create the thin-wrapper directory** in the scope selected at step 2 and add
   `scripts/` with standalone, executable, self-documenting tooling.

8. **Write the thin wrapper's `SKILL.md`.** Declare `name`, `description`, and
   `teleclaude_taxonomy: true`. Use one H1, optional `## Required reads` immediately
   after it, then `## Purpose`, `## Scope`, `## Inputs`, `## Outputs`, and
   `## Procedure`; optional `## See Also` comes last. Required reads point at the
   canonical snippets, while Procedure only explains how to invoke the packaged scripts.

9. **Keep package resources in their native formats.** Supporting Markdown is not
   taxonomy-validated; the opt-in applies only to the package's `SKILL.md` entrypoint.

10. **Run `telec sync`** to validate, render, and deploy through the common artifact
    pipeline.

11. **Verify** the skill appears at the intended global or project runtime scope,
    retains its supporting resources, and triggers correctly.

## Outputs

- An intact third-party skill incorporated by catalog link or project-local copy;
  or a TeleClaude thin wrapper with canonical doc references and scripts.
- A skill validated, rendered, and deployed via `telec sync`.

## Recovery

- If `telec sync` fails, fix the issue and rerun.
- If a first-party wrapper skipped the script gate, remove it and migrate its
  procedural content to an activatable doc snippet.
- If an incorporated third-party skill was rewritten into TeleClaude's taxonomy,
  restore the upstream package and remove `teleclaude_taxonomy`.
